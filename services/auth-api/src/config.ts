import { betterAuth, type BetterAuthOptions } from 'better-auth';
import { genericOAuth } from 'better-auth/plugins';

export const AUTH_BASE_PATH = '/api/auth';
export const COGNITO_PROVIDER_ID = 'cognito';
export const SESSION_MAX_AGE_SECONDS = 8 * 60 * 60;

export interface AuthRuntimeConfig {
  readonly baseUrl: string;
  readonly trustedOrigins: readonly string[];
  readonly cognitoIssuer: string;
  readonly cognitoDiscoveryUrl: string;
  readonly betterAuthSecretId: string;
  readonly cognitoClientSecretId: string;
}

export interface AuthRuntimeSecrets {
  readonly betterAuthSecret: string;
  readonly cognitoClientId: string;
  readonly cognitoClientSecret: string;
}

function required(environment: NodeJS.ProcessEnv, key: string): string {
  const value = environment[key]?.trim();
  if (!value) throw new Error(`Missing required environment variable: ${key}`);
  return value;
}

function normalizeOrigin(value: string, label: string): string {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error(`${label} must be an absolute URL`);
  }
  if (url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new Error(`${label} must be an origin without credentials, path, query, or fragment`);
  }
  const isLocalHttp =
    url.protocol === 'http:' && (url.hostname === 'localhost' || url.hostname === '127.0.0.1');
  if (url.protocol !== 'https:' && !isLocalHttp) {
    throw new Error(`${label} must use HTTPS except for localhost development`);
  }
  return url.origin;
}

function normalizeIssuer(value: string): string {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error('COGNITO_ISSUER must be an absolute URL');
  }
  if (
    url.protocol !== 'https:' ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    url.pathname === '/'
  ) {
    throw new Error('COGNITO_ISSUER must be an HTTPS issuer URL with a user-pool path');
  }
  return url.toString().replace(/\/$/, '');
}

export function readRuntimeConfig(
  environment: NodeJS.ProcessEnv = process.env,
  requestBaseUrl?: string,
): AuthRuntimeConfig {
  const baseUrl = normalizeOrigin(
    requestBaseUrl ?? required(environment, 'BETTER_AUTH_URL'),
    requestBaseUrl ? 'request base URL' : 'BETTER_AUTH_URL',
  );
  const configuredOrigins = required(environment, 'BETTER_AUTH_TRUSTED_ORIGINS')
    .split(',')
    .map((origin) => normalizeOrigin(origin.trim(), 'BETTER_AUTH_TRUSTED_ORIGINS'));
  const trustedOrigins = [...new Set([baseUrl, ...configuredOrigins])];

  const cognitoIssuer = normalizeIssuer(required(environment, 'COGNITO_ISSUER'));
  const cognitoDiscoveryUrl = `${cognitoIssuer}/.well-known/openid-configuration`;

  return {
    baseUrl,
    trustedOrigins,
    cognitoIssuer,
    cognitoDiscoveryUrl,
    betterAuthSecretId: required(environment, 'BETTER_AUTH_SECRET_ID'),
    cognitoClientSecretId: required(environment, 'COGNITO_CLIENT_SECRET_ID'),
  };
}

export function createCognitoProviderConfig(
  config: AuthRuntimeConfig,
  secrets: AuthRuntimeSecrets,
) {
  return {
    providerId: COGNITO_PROVIDER_ID,
    clientId: secrets.cognitoClientId,
    clientSecret: secrets.cognitoClientSecret,
    discoveryUrl: config.cognitoDiscoveryUrl,
    issuer: config.cognitoIssuer,
    requireIssuerValidation: false,
    scopes: ['openid', 'email', 'profile'],
    pkce: true,
    authentication: 'basic' as const,
    disableImplicitSignUp: false,
    disableSignUp: false,
  };
}

export function createBetterAuthOptions(
  config: AuthRuntimeConfig,
  secrets: AuthRuntimeSecrets,
): BetterAuthOptions {
  return {
    appName: 'VETTED',
    baseURL: config.baseUrl,
    basePath: AUTH_BASE_PATH,
    secret: secrets.betterAuthSecret,
    trustedOrigins: [...config.trustedOrigins],
    session: {
      expiresIn: SESSION_MAX_AGE_SECONDS,
      updateAge: 60 * 60,
      cookieCache: {
        enabled: true,
        maxAge: SESSION_MAX_AGE_SECONDS,
        strategy: 'jwe',
        refreshCache: { updateAge: 60 * 60 },
        version: '1',
      },
    },
    account: {
      storeStateStrategy: 'cookie',
      storeAccountCookie: true,
      encryptOAuthTokens: true,
    },
    advanced: {
      useSecureCookies: true,
      cookiePrefix: 'vetted',
      defaultCookieAttributes: {
        httpOnly: true,
        secure: true,
        sameSite: 'lax',
        path: '/',
      },
    },
    rateLimit: {
      enabled: true,
      storage: 'memory',
      window: 60,
      max: 60,
    },
    telemetry: { enabled: false },
    logger: { disabled: true },
    plugins: [
      genericOAuth({
        config: [createCognitoProviderConfig(config, secrets)],
      }),
    ],
  } satisfies BetterAuthOptions;
}

export function createAuthServer(config: AuthRuntimeConfig, secrets: AuthRuntimeSecrets) {
  return betterAuth(createBetterAuthOptions(config, secrets));
}
