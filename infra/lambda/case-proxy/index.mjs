// @ts-nocheck
/**
 * CSUB case-proxy Lambda (deployable runtime artifact).
 *
 * This is the committed, dependency-light runtime handler that the CDK
 * PlatformStack packages as the Lambda asset (guaranteeing offline synth). Its
 * logic mirrors the typed, unit-tested source of truth in
 * services/case-api/src/. It uses only AWS SDK v3 modular clients (never
 * `fetch`), initialized once outside the handler.
 *
 * Security invariants (issue #20):
 * - Reaches AgentCore Runtime via the SDK v3 data-plane client (SigV4), never fetch.
 * - Allowlists headers/context sent downstream; never forwards Host/Authorization.
 * - Caps the JSON metadata surface at <= 1 MiB and returns safe, correlation-ID errors.
 * - Evidence is uploaded via case-scoped presigned S3 PUTs, not through the API.
 * - Never logs request bodies, tokens, secrets, or PII.
 */
import { createHash, randomUUID } from 'node:crypto';
import { S3Client, PutObjectCommand, GetObjectCommand } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
import { SQSClient, SendMessageCommand } from '@aws-sdk/client-sqs';
import {
  BedrockAgentCoreClient,
  InvokeAgentRuntimeCommand,
} from '@aws-sdk/client-bedrock-agentcore';

const REGION = process.env.AWS_REGION;
const MAX_JSON_BYTES = Number.parseInt(process.env.MAX_JSON_BYTES ?? '1048576', 10);
const PRESIGN_TTL_SECONDS = Number.parseInt(process.env.PRESIGN_TTL_SECONDS ?? '300', 10);
const EVIDENCE_BUCKET = process.env.EVIDENCE_BUCKET;
const GENERATED_BUCKET = process.env.GENERATED_BUCKET;
const ANALYSIS_QUEUE_URL = process.env.ANALYSIS_QUEUE_URL;
const AGENT_RUNTIME_ENDPOINT_ARN = process.env.AGENT_RUNTIME_ENDPOINT_ARN;

// Only these inbound headers/context values may travel to AgentCore.
const HEADER_ALLOWLIST = new Set(['content-type', 'x-correlation-id']);

// Clients initialized once (outside the handler) for connection reuse.
const s3 = new S3Client({ region: REGION });
const sqs = new SQSClient({ region: REGION });
const agentCore = new BedrockAgentCoreClient({ region: REGION });

const json = (statusCode, body, correlationId) => ({
  statusCode,
  headers: {
    'Content-Type': 'application/json',
    'X-Correlation-Id': correlationId,
    'Cache-Control': 'no-store',
  },
  body: JSON.stringify(body),
});

const errorResponse = (statusCode, code, correlationId) =>
  json(statusCode, { error: code, correlationId }, correlationId);

/** Safe alphanumeric case-id validation to prevent key/path traversal. */
const isSafeId = (value) => typeof value === 'string' && /^[A-Za-z0-9._-]{1,128}$/.test(value);

/** Allowlist headers and drop Host/Authorization before sending downstream. */
export const filterHeaders = (headers) => {
  const out = {};
  for (const [key, value] of Object.entries(headers ?? {})) {
    if (HEADER_ALLOWLIST.has(key.toLowerCase())) out[key] = value;
  }
  return out;
};

const hashToken = (token) => createHash('sha256').update(token, 'utf8').digest('hex');

const INVITE_TOKEN_MIN = 16;
const INVITE_TOKEN_MAX = 512;

/**
 * Extract and validate an opaque invite token from Authorization: Bearer.
 * Requires the exact `Bearer ` scheme and an opaque token within size bounds.
 * Returns null for missing/malformed/oversized tokens; never echoes the token.
 * The token must NEVER appear in the URL path or query.
 */
export const extractBearerToken = (headers = {}) => {
  const auth = headers.authorization ?? headers.Authorization;
  if (typeof auth !== 'string') return null;
  const prefix = 'Bearer ';
  if (!auth.startsWith(prefix)) return null;
  const token = auth.slice(prefix.length);
  if (!/^[A-Za-z0-9._~+/=-]+$/.test(token)) return null;
  if (token.length < INVITE_TOKEN_MIN || token.length > INVITE_TOKEN_MAX) return null;
  return token;
};

async function issueEvidenceUpload(caseId, correlationId) {
  const key = `evidence/${caseId}/${randomUUID()}`;
  const command = new PutObjectCommand({
    Bucket: EVIDENCE_BUCKET,
    Key: key,
    ServerSideEncryption: 'aws:kms',
  });
  const uploadUrl = await getSignedUrl(s3, command, { expiresIn: PRESIGN_TTL_SECONDS });
  return json(201, { key, uploadUrl, expiresIn: PRESIGN_TTL_SECONDS }, correlationId);
}

async function issuePacketDownload(caseId, correlationId) {
  const command = new GetObjectCommand({
    Bucket: GENERATED_BUCKET,
    Key: `packets/${caseId}/latest.json`,
  });
  const downloadUrl = await getSignedUrl(s3, command, { expiresIn: PRESIGN_TTL_SECONDS });
  return json(200, { downloadUrl, expiresIn: PRESIGN_TTL_SECONDS }, correlationId);
}

async function forwardToAgentCore(routeKey, payload, correlationId) {
  if (!AGENT_RUNTIME_ENDPOINT_ARN) {
    return errorResponse(503, 'agent_runtime_unavailable', correlationId);
  }
  const command = new InvokeAgentRuntimeCommand({
    agentRuntimeArn: AGENT_RUNTIME_ENDPOINT_ARN,
    runtimeSessionId: correlationId.padEnd(33, '0'),
    contentType: 'application/json',
    accept: 'application/json',
    payload: new TextEncoder().encode(
      JSON.stringify({ route: routeKey, correlationId, input: payload }),
    ),
  });
  const result = await agentCore.send(command);
  const text = result.response ? Buffer.from(result.response).toString('utf8') : '{}';
  return {
    statusCode: result.statusCode ?? 200,
    headers: {
      'Content-Type': 'application/json',
      'X-Correlation-Id': correlationId,
      'Cache-Control': 'no-store',
    },
    body: text,
  };
}

export async function handler(event, context) {
  const correlationId =
    event?.headers?.['x-correlation-id'] ?? context?.awsRequestId ?? randomUUID();
  const routeKey = event?.routeKey ?? '';
  const method = event?.requestContext?.http?.method ?? 'GET';
  const pathParams = event?.pathParameters ?? {};

  try {
    // Enforce the <= 1 MiB JSON metadata surface for write requests.
    if (event?.body) {
      const size = Buffer.byteLength(event.body, event.isBase64Encoded ? 'base64' : 'utf8');
      if (size > MAX_JSON_BYTES) {
        return errorResponse(413, 'payload_too_large', correlationId);
      }
    }

    let parsedBody = {};
    if (event?.body && method !== 'GET') {
      try {
        parsedBody = JSON.parse(
          event.isBase64Encoded ? Buffer.from(event.body, 'base64').toString('utf8') : event.body,
        );
      } catch {
        return errorResponse(400, 'invalid_json', correlationId);
      }
    }

    const caseId = pathParams.id;
    if (routeKey.includes('{id}') && caseId && !isSafeId(caseId)) {
      return errorResponse(400, 'invalid_identifier', correlationId);
    }

    // Case-scoped presigned evidence upload (no bytes through the API).
    if (routeKey === 'POST /cases/{id}/documents') {
      return await issueEvidenceUpload(caseId, correlationId);
    }
    // Presigned packet download.
    if (routeKey === 'GET /cases/{id}/packet') {
      return await issuePacketDownload(caseId, correlationId);
    }
    // Invite intake: read the opaque token ONLY from Authorization: Bearer
    // (never path/query), so it cannot leak into gateway/CDN/browser/logs.
    if (routeKey === 'GET /intake' || routeKey === 'POST /intake') {
      const token = extractBearerToken(event.headers);
      if (token === null) {
        return errorResponse(401, 'invalid_invite', correlationId);
      }
      // Hash in Lambda; forward only the hash plus allowlisted context (which
      // excludes Authorization). The raw token never leaves this function.
      return await forwardToAgentCore(
        routeKey,
        { token_hash: hashToken(token), headers: filterHeaders(event.headers) },
        correlationId,
      );
    }
    // Async analysis enqueue.
    if (routeKey === 'POST /cases/{id}/analyze') {
      if (!ANALYSIS_QUEUE_URL) return errorResponse(503, 'queue_unavailable', correlationId);
      await sqs.send(
        new SendMessageCommand({
          QueueUrl: ANALYSIS_QUEUE_URL,
          MessageBody: JSON.stringify({ case_id: caseId, correlationId, input: parsedBody }),
        }),
      );
      return json(202, { status: 'queued', correlationId }, correlationId);
    }

    // Everything else routes to the AgentCore runtime.
    return await forwardToAgentCore(routeKey, parsedBody, correlationId);
  } catch (error) {
    // Log only non-sensitive, structured metadata — never bodies/tokens/secrets.
    console.error(
      JSON.stringify({
        level: 'error',
        correlationId,
        routeKey,
        name: error?.name ?? 'Error',
      }),
    );
    return errorResponse(502, 'gateway_error', correlationId);
  }
}
