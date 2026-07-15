import type {
  APIGatewayProxyEventV2,
  APIGatewayProxyStructuredResultV2,
  Context,
} from 'aws-lambda';

import { createAuthServer, readRuntimeConfig, type AuthRuntimeConfig } from './config.js';
import { loadRuntimeSecrets } from './secrets.js';

type WebAuthHandler = (request: Request) => Promise<Response>;
type AuthHandlerResolver = (config: AuthRuntimeConfig) => Promise<WebAuthHandler>;

const authHandlers = new Map<string, Promise<WebAuthHandler>>();

async function resolveAuthHandler(config: AuthRuntimeConfig): Promise<WebAuthHandler> {
  let handler = authHandlers.get(config.baseUrl);
  if (!handler) {
    handler = loadRuntimeSecrets(config).then(
      (secrets) => createAuthServer(config, secrets).handler,
    );
    authHandlers.set(config.baseUrl, handler);
  }
  return handler;
}

function requestHeaders(event: APIGatewayProxyEventV2): Headers {
  const headers = new Headers();
  for (const [name, value] of Object.entries(event.headers ?? {})) {
    if (value !== undefined && name.toLowerCase() !== 'host') headers.set(name, value);
  }
  if (event.cookies?.length && !headers.has('cookie')) {
    headers.set('cookie', event.cookies.join('; '));
  }
  return headers;
}

export function requestBaseUrl(event: APIGatewayProxyEventV2): string | undefined {
  const host = event.headers?.['x-vetted-host'] ?? event.headers?.['X-Vetted-Host'];
  if (host === undefined) return undefined;
  if (!/^[a-z0-9](?:[a-z0-9-]{0,62})\.cloudfront\.net$/.test(host)) {
    throw new Error('Untrusted CloudFront host');
  }
  return `https://${host}`;
}

export function toWebRequest(event: APIGatewayProxyEventV2, baseUrl: string): Request {
  const method = event.requestContext?.http?.method ?? 'GET';
  const query = event.rawQueryString ? `?${event.rawQueryString}` : '';
  const url = new URL(`${event.rawPath || '/'}${query}`, baseUrl);
  const hasBody = method !== 'GET' && method !== 'HEAD' && event.body !== undefined;
  const body = hasBody
    ? Buffer.from(event.body!, event.isBase64Encoded ? 'base64' : 'utf8')
    : undefined;
  return new Request(url, {
    method,
    headers: requestHeaders(event),
    body,
  });
}

function responseCookies(headers: Headers): string[] {
  const getSetCookie = (headers as Headers & { getSetCookie?: () => string[] }).getSetCookie;
  if (typeof getSetCookie === 'function') return getSetCookie.call(headers);
  const cookie = headers.get('set-cookie');
  return cookie ? [cookie] : [];
}

export async function toLambdaResponse(
  response: Response,
): Promise<APIGatewayProxyStructuredResultV2> {
  const headers: Record<string, string> = {};
  response.headers.forEach((value, name) => {
    if (name.toLowerCase() !== 'set-cookie') headers[name] = value;
  });
  headers['cache-control'] = 'no-store, max-age=0';
  headers.pragma = 'no-cache';

  return {
    statusCode: response.status,
    headers,
    cookies: responseCookies(response.headers),
    body: response.status === 204 || response.status === 304 ? undefined : await response.text(),
    isBase64Encoded: false,
  };
}

function configurationError(requestId: string): APIGatewayProxyStructuredResultV2 {
  return {
    statusCode: 503,
    headers: {
      'content-type': 'application/json',
      'cache-control': 'no-store, max-age=0',
      pragma: 'no-cache',
    },
    body: JSON.stringify({ error: 'auth_configuration_unavailable', requestId }),
    isBase64Encoded: false,
  };
}

export function createLambdaHandler(resolveHandler: AuthHandlerResolver) {
  return async (
    event: APIGatewayProxyEventV2,
    context: Context,
  ): Promise<APIGatewayProxyStructuredResultV2> => {
    try {
      const config = readRuntimeConfig(process.env, requestBaseUrl(event));
      const authHandler = await resolveHandler(config);
      return await toLambdaResponse(await authHandler(toWebRequest(event, config.baseUrl)));
    } catch (error) {
      console.error(
        JSON.stringify({
          level: 'error',
          event: 'auth_request_failed',
          requestId: context.awsRequestId,
          errorName: error instanceof Error ? error.name : 'UnknownError',
        }),
      );
      return configurationError(context.awsRequestId);
    }
  };
}

export const handler = createLambdaHandler(resolveAuthHandler);
