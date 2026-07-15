import { describe, expect, test, vi } from 'vitest';
import type { APIGatewayProxyEventV2 } from 'aws-lambda';
import {
  ProxyConfig,
  ProxyDeps,
  createHandler,
  exceedsBodyLimit,
  filterHeaders,
  hashToken,
  isSafeId,
  toSessionId,
} from '../src/index.js';

const config: ProxyConfig = {
  region: 'us-west-2',
  maxJsonBytes: 1048576,
  presignTtlSeconds: 300,
  evidenceBucket: 'evidence-bucket',
  generatedBucket: 'generated-bucket',
  analysisQueueUrl: 'https://sqs.example/queue',
  agentRuntimeEndpointArn: 'arn:aws:bedrock-agentcore:us-west-2:111111111111:runtime/r/runtime-endpoint/e',
};

function makeDeps(overrides: Partial<ProxyDeps> = {}): ProxyDeps {
  return {
    presignPut: vi.fn(async (_b, k) => `https://signed.put/${k}`),
    presignGet: vi.fn(async (_b, k) => `https://signed.get/${k}`),
    sendToQueue: vi.fn(async () => undefined),
    invokeAgent: vi.fn(async () => ({ statusCode: 200, body: '{"ok":true}' })),
    ...overrides,
  };
}

function event(partial: Partial<APIGatewayProxyEventV2>): APIGatewayProxyEventV2 {
  return {
    version: '2.0',
    routeKey: partial.routeKey ?? '$default',
    rawPath: '/',
    rawQueryString: '',
    headers: partial.headers ?? {},
    requestContext: {
      http: { method: partial.requestContext?.http?.method ?? 'GET' },
    } as APIGatewayProxyEventV2['requestContext'],
    isBase64Encoded: partial.isBase64Encoded ?? false,
    ...partial,
  } as APIGatewayProxyEventV2;
}

describe('pure helpers', () => {
  test('isSafeId rejects traversal and oversized ids', () => {
    expect(isSafeId('case-123_AB.9')).toBe(true);
    expect(isSafeId('../etc/passwd')).toBe(false);
    expect(isSafeId('a/b')).toBe(false);
    expect(isSafeId('x'.repeat(200))).toBe(false);
    expect(isSafeId(undefined)).toBe(false);
  });

  test('filterHeaders drops Host/Authorization, keeps only allowlisted', () => {
    const out = filterHeaders({
      Authorization: 'Bearer secret',
      host: 'evil.example',
      'Content-Type': 'application/json',
      'X-Correlation-Id': 'abc',
      'x-custom': 'nope',
    });
    expect(out).toEqual({ 'Content-Type': 'application/json', 'X-Correlation-Id': 'abc' });
    expect(out.Authorization).toBeUndefined();
    expect(out.host).toBeUndefined();
  });

  test('hashToken is deterministic sha256 hex and hides plaintext', () => {
    const h = hashToken('super-secret-invite-token');
    expect(h).toMatch(/^[0-9a-f]{64}$/);
    expect(h).not.toContain('super-secret');
    expect(hashToken('a')).toBe(hashToken('a'));
    expect(hashToken('a')).not.toBe(hashToken('b'));
  });

  test('exceedsBodyLimit enforces the <= 1 MiB cap', () => {
    expect(exceedsBodyLimit('x'.repeat(10), false, 1048576)).toBe(false);
    expect(exceedsBodyLimit('x'.repeat(1048577), false, 1048576)).toBe(true);
    expect(exceedsBodyLimit(undefined, false, 1048576)).toBe(false);
  });

  test('toSessionId pads to the AgentCore 33-char minimum', () => {
    expect(toSessionId('short').length).toBeGreaterThanOrEqual(33);
    const long = 'x'.repeat(40);
    expect(toSessionId(long)).toBe(long);
  });
});

describe('handler routing and security', () => {
  test('rejects oversized bodies with 413', async () => {
    const deps = makeDeps();
    const handler = createHandler(config, deps);
    const res = await handler(
      event({
        routeKey: 'POST /cases',
        requestContext: { http: { method: 'POST' } } as APIGatewayProxyEventV2['requestContext'],
        body: 'x'.repeat(1048577),
      }),
    );
    expect(res.statusCode).toBe(413);
    expect(deps.invokeAgent).not.toHaveBeenCalled();
  });

  test('rejects invalid JSON with 400', async () => {
    const handler = createHandler(config, makeDeps());
    const res = await handler(
      event({
        routeKey: 'POST /cases',
        requestContext: { http: { method: 'POST' } } as APIGatewayProxyEventV2['requestContext'],
        body: '{not json',
      }),
    );
    expect(res.statusCode).toBe(400);
    expect(JSON.parse(res.body as string).error).toBe('invalid_json');
  });

  test('rejects unsafe case identifiers with 400', async () => {
    const handler = createHandler(config, makeDeps());
    const res = await handler(
      event({ routeKey: 'GET /cases/{id}/packet', pathParameters: { id: '../secret' } }),
    );
    expect(res.statusCode).toBe(400);
    expect(JSON.parse(res.body as string).error).toBe('invalid_identifier');
  });

  test('evidence upload returns a case-scoped presigned PUT (no bytes through API)', async () => {
    const deps = makeDeps();
    const handler = createHandler(config, deps);
    const res = await handler(
      event({
        routeKey: 'POST /cases/{id}/documents',
        pathParameters: { id: 'case-1' },
        requestContext: { http: { method: 'POST' } } as APIGatewayProxyEventV2['requestContext'],
      }),
    );
    expect(res.statusCode).toBe(201);
    const body = JSON.parse(res.body as string);
    expect(body.key).toMatch(/^evidence\/case-1\//);
    expect(body.uploadUrl).toContain('https://signed.put/');
    expect(deps.presignPut).toHaveBeenCalledWith('evidence-bucket', body.key, 300);
  });

  test('packet download returns a presigned GET', async () => {
    const deps = makeDeps();
    const handler = createHandler(config, deps);
    const res = await handler(
      event({ routeKey: 'GET /cases/{id}/packet', pathParameters: { id: 'case-1' } }),
    );
    expect(res.statusCode).toBe(200);
    expect(deps.presignGet).toHaveBeenCalledWith(
      'generated-bucket',
      'packets/case-1/latest.json',
      300,
    );
  });

  test('intake forwards only the token hash and allowlisted headers', async () => {
    const deps = makeDeps();
    const handler = createHandler(config, deps);
    const token = 'invite-token-abcdef123456';
    await handler(
      event({
        routeKey: 'GET /intake/{token}',
        pathParameters: { token },
        headers: { Authorization: 'Bearer x', 'x-correlation-id': 'corr-1' },
      }),
    );
    expect(deps.invokeAgent).toHaveBeenCalledTimes(1);
    const payload = (deps.invokeAgent as ReturnType<typeof vi.fn>).mock.calls[0][2] as {
      input: { token_hash: string; headers: Record<string, string> };
    };
    expect(payload.input.token_hash).toBe(hashToken(token));
    expect(JSON.stringify(payload)).not.toContain(token);
    expect(payload.input.headers.Authorization).toBeUndefined();
    expect(payload.input.headers['x-correlation-id']).toBe('corr-1');
  });

  test('short invite tokens are rejected before any downstream call', async () => {
    const deps = makeDeps();
    const handler = createHandler(config, deps);
    const res = await handler(
      event({ routeKey: 'POST /intake/{token}', pathParameters: { token: 'short' } }),
    );
    expect(res.statusCode).toBe(401);
    expect(deps.invokeAgent).not.toHaveBeenCalled();
  });

  test('analyze enqueues async work and returns 202', async () => {
    const deps = makeDeps();
    const handler = createHandler(config, deps);
    const res = await handler(
      event({
        routeKey: 'POST /cases/{id}/analyze',
        pathParameters: { id: 'case-1' },
        requestContext: { http: { method: 'POST' } } as APIGatewayProxyEventV2['requestContext'],
        body: JSON.stringify({ confirmed_match_id: 'm1' }),
      }),
    );
    expect(res.statusCode).toBe(202);
    expect(deps.sendToQueue).toHaveBeenCalledTimes(1);
  });

  test('returns 503 when the AgentCore endpoint is not configured', async () => {
    const handler = createHandler({ ...config, agentRuntimeEndpointArn: undefined }, makeDeps());
    const res = await handler(
      event({ routeKey: 'GET /cases/{id}', pathParameters: { id: 'case-1' } }),
    );
    expect(res.statusCode).toBe(503);
    expect(JSON.parse(res.body as string).error).toBe('agent_runtime_unavailable');
  });

  test('downstream failures produce a safe 502 with a correlation id and no leakage', async () => {
    const deps = makeDeps({
      invokeAgent: vi.fn(async () => {
        throw new Error('secret-internal-detail');
      }),
    });
    const handler = createHandler(config, deps);
    const res = await handler(
      event({ routeKey: 'GET /cases/{id}', pathParameters: { id: 'case-1' } }),
    );
    expect(res.statusCode).toBe(502);
    const body = JSON.parse(res.body as string);
    expect(body.error).toBe('gateway_error');
    expect(body.correlationId).toBeDefined();
    expect(res.body as string).not.toContain('secret-internal-detail');
  });
});
