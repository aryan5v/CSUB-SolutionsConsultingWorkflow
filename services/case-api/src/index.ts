import { createHash, randomUUID } from 'node:crypto';
import type {
  APIGatewayProxyEventV2,
  APIGatewayProxyStructuredResultV2,
  Context,
} from 'aws-lambda';
import { S3Client, PutObjectCommand, GetObjectCommand } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
import { SQSClient, SendMessageCommand } from '@aws-sdk/client-sqs';
import {
  BedrockAgentCoreClient,
  InvokeAgentRuntimeCommand,
} from '@aws-sdk/client-bedrock-agentcore';

/**
 * CSUB case-proxy Lambda — typed, unit-tested source of truth.
 *
 * The deployed runtime artifact (infra/lambda/case-proxy/index.mjs) mirrors
 * this logic; `npm run build` bundles this module to the same shape. All AWS
 * access uses AWS SDK v3 modular clients; AgentCore is reached via the
 * data-plane client (SigV4), never `fetch`. See the security invariants
 * documented on the deployed artifact and in issue #20.
 */

/** Inbound headers permitted to travel downstream. Host/Authorization excluded. */
export const HEADER_ALLOWLIST = new Set(['content-type', 'x-correlation-id']);

export interface ProxyConfig {
  readonly region?: string;
  readonly maxJsonBytes: number;
  readonly presignTtlSeconds: number;
  readonly evidenceBucket?: string;
  readonly generatedBucket?: string;
  readonly analysisQueueUrl?: string;
  readonly agentRuntimeEndpointArn?: string;
}

export interface AgentResult {
  readonly statusCode: number;
  readonly body: string;
}

/** Side-effecting dependencies, injected for hermetic unit tests. */
export interface ProxyDeps {
  presignPut(bucket: string, key: string, ttlSeconds: number): Promise<string>;
  presignGet(bucket: string, key: string, ttlSeconds: number): Promise<string>;
  sendToQueue(queueUrl: string, body: string): Promise<void>;
  invokeAgent(endpointArn: string, sessionId: string, payload: unknown): Promise<AgentResult>;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): ProxyConfig {
  return {
    region: env.AWS_REGION,
    maxJsonBytes: Number.parseInt(env.MAX_JSON_BYTES ?? '1048576', 10),
    presignTtlSeconds: Number.parseInt(env.PRESIGN_TTL_SECONDS ?? '300', 10),
    evidenceBucket: env.EVIDENCE_BUCKET,
    generatedBucket: env.GENERATED_BUCKET,
    analysisQueueUrl: env.ANALYSIS_QUEUE_URL,
    agentRuntimeEndpointArn: env.AGENT_RUNTIME_ENDPOINT_ARN,
  };
}

// -- Pure helpers (unit-tested directly) ---------------------------------

/** Restrict identifiers to a safe charset to prevent key/path traversal. */
export function isSafeId(value: unknown): value is string {
  return typeof value === 'string' && /^[A-Za-z0-9._-]{1,128}$/.test(value);
}

/** Keep only allowlisted headers; drop Host/Authorization and everything else. */
export function filterHeaders(headers: Record<string, string | undefined> = {}): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(headers)) {
    if (value !== undefined && HEADER_ALLOWLIST.has(key.toLowerCase())) {
      out[key] = value;
    }
  }
  return out;
}

/** SHA-256 hex of an opaque invite token — only the hash is ever persisted/forwarded. */
export function hashToken(token: string): string {
  return createHash('sha256').update(token, 'utf8').digest('hex');
}

/** True when the (possibly base64) body exceeds the configured JSON cap. */
export function exceedsBodyLimit(
  body: string | undefined,
  isBase64Encoded: boolean,
  maxJsonBytes: number,
): boolean {
  if (!body) return false;
  return Buffer.byteLength(body, isBase64Encoded ? 'base64' : 'utf8') > maxJsonBytes;
}

export function jsonResponse(
  statusCode: number,
  body: unknown,
  correlationId: string,
): APIGatewayProxyStructuredResultV2 {
  return {
    statusCode,
    headers: {
      'Content-Type': 'application/json',
      'X-Correlation-Id': correlationId,
      'Cache-Control': 'no-store',
    },
    body: JSON.stringify(body),
  };
}

/** Safe, correlation-ID-tagged error envelope — never leaks internals. */
export function errorResponse(
  statusCode: number,
  code: string,
  correlationId: string,
): APIGatewayProxyStructuredResultV2 {
  return jsonResponse(statusCode, { error: code, correlationId }, correlationId);
}

export function evidenceKey(caseId: string): string {
  return `evidence/${caseId}/${randomUUID()}`;
}

/** AgentCore requires a runtimeSessionId of at least 33 characters. */
export function toSessionId(correlationId: string): string {
  return correlationId.length >= 33 ? correlationId : correlationId.padEnd(33, '0');
}

// -- Live dependency implementations -------------------------------------

function createLiveDeps(config: ProxyConfig): ProxyDeps {
  const s3 = new S3Client({ region: config.region });
  const sqs = new SQSClient({ region: config.region });
  const agentCore = new BedrockAgentCoreClient({ region: config.region });

  return {
    presignPut: (bucket, key, ttlSeconds) =>
      getSignedUrl(
        s3,
        new PutObjectCommand({ Bucket: bucket, Key: key, ServerSideEncryption: 'aws:kms' }),
        { expiresIn: ttlSeconds },
      ),
    presignGet: (bucket, key, ttlSeconds) =>
      getSignedUrl(s3, new GetObjectCommand({ Bucket: bucket, Key: key }), {
        expiresIn: ttlSeconds,
      }),
    sendToQueue: async (queueUrl, body) => {
      await sqs.send(new SendMessageCommand({ QueueUrl: queueUrl, MessageBody: body }));
    },
    invokeAgent: async (endpointArn, sessionId, payload) => {
      const result = await agentCore.send(
        new InvokeAgentRuntimeCommand({
          agentRuntimeArn: endpointArn,
          runtimeSessionId: sessionId,
          contentType: 'application/json',
          accept: 'application/json',
          payload: new TextEncoder().encode(JSON.stringify(payload)),
        }),
      );
      const body = result.response ? await result.response.transformToString() : '{}';
      return { statusCode: result.statusCode ?? 200, body };
    },
  };
}

// -- Handler factory ------------------------------------------------------

export function createHandler(config: ProxyConfig, deps: ProxyDeps) {
  return async function handler(
    event: APIGatewayProxyEventV2,
    context?: Context,
  ): Promise<APIGatewayProxyStructuredResultV2> {
    const correlationId =
      event.headers?.['x-correlation-id'] ?? context?.awsRequestId ?? randomUUID();
    const routeKey = event.routeKey ?? '';
    const method = event.requestContext?.http?.method ?? 'GET';
    const pathParams = event.pathParameters ?? {};

    try {
      if (exceedsBodyLimit(event.body, Boolean(event.isBase64Encoded), config.maxJsonBytes)) {
        return errorResponse(413, 'payload_too_large', correlationId);
      }

      let parsedBody: unknown = {};
      if (event.body && method !== 'GET') {
        try {
          const raw = event.isBase64Encoded
            ? Buffer.from(event.body, 'base64').toString('utf8')
            : event.body;
          parsedBody = JSON.parse(raw);
        } catch {
          return errorResponse(400, 'invalid_json', correlationId);
        }
      }

      const caseId = pathParams.id;
      if (routeKey.includes('{id}') && caseId !== undefined && !isSafeId(caseId)) {
        return errorResponse(400, 'invalid_identifier', correlationId);
      }

      if (routeKey === 'POST /cases/{id}/documents') {
        if (!config.evidenceBucket) return errorResponse(503, 'storage_unavailable', correlationId);
        const key = evidenceKey(caseId as string);
        const uploadUrl = await deps.presignPut(
          config.evidenceBucket,
          key,
          config.presignTtlSeconds,
        );
        return jsonResponse(
          201,
          { key, uploadUrl, expiresIn: config.presignTtlSeconds },
          correlationId,
        );
      }

      if (routeKey === 'GET /cases/{id}/packet') {
        if (!config.generatedBucket)
          return errorResponse(503, 'storage_unavailable', correlationId);
        const downloadUrl = await deps.presignGet(
          config.generatedBucket,
          `packets/${caseId}/latest.json`,
          config.presignTtlSeconds,
        );
        return jsonResponse(
          200,
          { downloadUrl, expiresIn: config.presignTtlSeconds },
          correlationId,
        );
      }

      if (routeKey.startsWith('GET /intake/') || routeKey.startsWith('POST /intake/')) {
        const token = pathParams.token;
        if (typeof token !== 'string' || token.length < 16) {
          return errorResponse(401, 'invalid_invite', correlationId);
        }
        if (!config.agentRuntimeEndpointArn) {
          return errorResponse(503, 'agent_runtime_unavailable', correlationId);
        }
        // Forward only the token HASH plus allowlisted headers — never plaintext.
        const result = await deps.invokeAgent(
          config.agentRuntimeEndpointArn,
          toSessionId(correlationId),
          {
            route: routeKey,
            correlationId,
            input: { token_hash: hashToken(token), headers: filterHeaders(event.headers) },
          },
        );
        return { statusCode: result.statusCode, headers: baseHeaders(correlationId), body: result.body };
      }

      if (routeKey === 'POST /cases/{id}/analyze') {
        if (!config.analysisQueueUrl) return errorResponse(503, 'queue_unavailable', correlationId);
        await deps.sendToQueue(
          config.analysisQueueUrl,
          JSON.stringify({ case_id: caseId, correlationId, input: parsedBody }),
        );
        return jsonResponse(202, { status: 'queued', correlationId }, correlationId);
      }

      if (!config.agentRuntimeEndpointArn) {
        return errorResponse(503, 'agent_runtime_unavailable', correlationId);
      }
      const result = await deps.invokeAgent(config.agentRuntimeEndpointArn, toSessionId(correlationId), {
        route: routeKey,
        correlationId,
        input: parsedBody,
      });
      return { statusCode: result.statusCode, headers: baseHeaders(correlationId), body: result.body };
    } catch (error) {
      // Log only non-sensitive, structured metadata — never bodies/tokens/secrets.
      const name = error instanceof Error ? error.name : 'Error';
      console.error(JSON.stringify({ level: 'error', correlationId, routeKey, name }));
      return errorResponse(502, 'gateway_error', correlationId);
    }
  };
}

function baseHeaders(correlationId: string): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    'X-Correlation-Id': correlationId,
    'Cache-Control': 'no-store',
  };
}

const config = loadConfig();
export const handler = createHandler(config, createLiveDeps(config));
