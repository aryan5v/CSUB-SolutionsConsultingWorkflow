import type { APIGatewayProxyEventV2, Context } from 'aws-lambda';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import {
  createLambdaHandler,
  requestBaseUrl,
  toLambdaResponse,
  toWebRequest,
} from '../src/handler.js';

const baseEvent: APIGatewayProxyEventV2 = {
  version: '2.0',
  routeKey: '$default',
  rawPath: '/api/auth/get-session',
  rawQueryString: 'fresh=true',
  headers: {
    'content-type': 'application/json',
    origin: 'https://example.cloudfront.net',
    host: 'function-id.lambda-url.us-west-2.on.aws',
  },
  cookies: ['vetted.session=encrypted', 'vetted.state=state'],
  requestContext: {
    accountId: 'anonymous',
    apiId: 'function-url',
    domainName: 'function-id.lambda-url.us-west-2.on.aws',
    domainPrefix: 'function-id',
    http: {
      method: 'POST',
      path: '/api/auth/get-session',
      protocol: 'HTTP/1.1',
      sourceIp: '203.0.113.10',
      userAgent: 'vitest',
    },
    requestId: 'request-id',
    routeKey: '$default',
    stage: '$default',
    time: '15/Jul/2026:00:00:00 +0000',
    timeEpoch: 0,
  },
  body: Buffer.from('{"ok":true}').toString('base64'),
  isBase64Encoded: true,
};

const context = { awsRequestId: 'lambda-request-id' } as Context;

beforeEach(() => {
  process.env.BETTER_AUTH_URL = 'https://example.cloudfront.net';
  process.env.BETTER_AUTH_TRUSTED_ORIGINS =
    'https://example.cloudfront.net,http://127.0.0.1:5173,http://localhost:5173';
  process.env.COGNITO_ISSUER =
    'https://cognito-idp.us-west-2.amazonaws.com/us-west-2_example';
  process.env.BETTER_AUTH_SECRET_ID = 'arn:better-auth';
  process.env.COGNITO_CLIENT_SECRET_ID = 'arn:cognito';
});

describe('Lambda Function URL adapter', () => {
  test('accepts only a CloudFront viewer host forwarded by the distribution', () => {
    expect(
      requestBaseUrl({
        ...baseEvent,
        headers: { ...baseEvent.headers, 'x-vetted-host': 'd123example.cloudfront.net' },
      }),
    ).toBe('https://d123example.cloudfront.net');
    expect(() =>
      requestBaseUrl({
        ...baseEvent,
        headers: { ...baseEvent.headers, 'x-vetted-host': 'evil.example' },
      }),
    ).toThrow(/Untrusted CloudFront host/);
  });

  test('preserves the same-origin path, query, cookies, origin, method, and decoded body', async () => {
    const request = toWebRequest(baseEvent, 'https://example.cloudfront.net');
    expect(request.url).toBe('https://example.cloudfront.net/api/auth/get-session?fresh=true');
    expect(request.method).toBe('POST');
    expect(request.headers.get('host')).toBeNull();
    expect(request.headers.get('origin')).toBe('https://example.cloudfront.net');
    expect(request.headers.get('cookie')).toBe('vetted.session=encrypted; vetted.state=state');
    await expect(request.json()).resolves.toEqual({ ok: true });
  });

  test('returns every Set-Cookie header and always disables browser/CDN caching', async () => {
    const headers = new Headers({ 'content-type': 'application/json', 'cache-control': 'public' });
    headers.append('set-cookie', 'vetted.session=one; Secure; HttpOnly; SameSite=Lax; Path=/');
    headers.append('set-cookie', 'vetted.state=two; Secure; HttpOnly; SameSite=Lax; Path=/');
    const result = await toLambdaResponse(new Response('{"session":true}', { headers }));
    expect(result.statusCode).toBe(200);
    expect(result.headers).toMatchObject({
      'cache-control': 'no-store, max-age=0',
      pragma: 'no-cache',
    });
    expect(result.cookies).toEqual([
      'vetted.session=one; Secure; HttpOnly; SameSite=Lax; Path=/',
      'vetted.state=two; Secure; HttpOnly; SameSite=Lax; Path=/',
    ]);
    expect(result.body).toBe('{"session":true}');
  });

  test('delegates to the Better Auth web handler', async () => {
    const authHandler = vi.fn(async () =>
      new Response(null, {
        status: 302,
        headers: { location: 'https://cognito.example/oauth2/authorize' },
      }),
    );
    const handler = createLambdaHandler(async () => authHandler);
    const result = await handler(baseEvent, context);
    expect(authHandler).toHaveBeenCalledOnce();
    expect(result.statusCode).toBe(302);
    expect(result.headers?.location).toBe('https://cognito.example/oauth2/authorize');
    expect(result.headers?.['cache-control']).toBe('no-store, max-age=0');
  });

  test('fails closed without returning secret/configuration details', async () => {
    const log = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const handler = createLambdaHandler(async () => {
      throw new Error('secret-value-that-must-not-leak');
    });
    const result = await handler(baseEvent, context);
    expect(result.statusCode).toBe(503);
    expect(result.body).toBe(
      JSON.stringify({
        error: 'auth_configuration_unavailable',
        requestId: 'lambda-request-id',
      }),
    );
    expect(JSON.stringify(result)).not.toContain('secret-value-that-must-not-leak');
    expect(log).toHaveBeenCalledWith(expect.not.stringContaining('secret-value-that-must-not-leak'));
    log.mockRestore();
  });
});
