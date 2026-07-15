import { describe, expect, test } from 'vitest';

import {
  AUTH_BASE_PATH,
  COGNITO_PROVIDER_ID,
  SESSION_MAX_AGE_SECONDS,
  createBetterAuthOptions,
  createCognitoProviderConfig,
  readRuntimeConfig,
  type AuthRuntimeConfig,
  type AuthRuntimeSecrets,
} from '../src/config.js';

const config: AuthRuntimeConfig = {
  baseUrl: 'https://example.cloudfront.net',
  trustedOrigins: [
    'https://example.cloudfront.net',
    'http://127.0.0.1:5173',
    'http://localhost:5173',
  ],
  cognitoIssuer: 'https://cognito-idp.us-west-2.amazonaws.com/us-west-2_example',
  cognitoDiscoveryUrl:
    'https://cognito-idp.us-west-2.amazonaws.com/us-west-2_example/.well-known/openid-configuration',
  betterAuthSecretId: 'arn:aws:secretsmanager:us-west-2:111111111111:secret:better-auth',
  cognitoClientSecretId: 'arn:aws:secretsmanager:us-west-2:111111111111:secret:cognito',
};

const secrets: AuthRuntimeSecrets = {
  betterAuthSecret: 'b'.repeat(64),
  cognitoClientId: 'client-id',
  cognitoClientSecret: 'cognito-client-secret',
};

describe('Better Auth configuration', () => {
  test('uses stateless encrypted same-origin cookie sessions with CSRF checks enabled', () => {
    const options = createBetterAuthOptions(config, secrets);
    expect(options.appName).toBe('VETTED');
    expect(options.database).toBeUndefined();
    expect(options.baseURL).toBe(config.baseUrl);
    expect(options.basePath).toBe(AUTH_BASE_PATH);
    expect(options.trustedOrigins).toEqual(config.trustedOrigins);
    expect(options.session?.expiresIn).toBe(SESSION_MAX_AGE_SECONDS);
    expect(options.session?.cookieCache).toMatchObject({
      enabled: true,
      maxAge: SESSION_MAX_AGE_SECONDS,
      strategy: 'jwe',
      refreshCache: { updateAge: 3600 },
      version: '1',
    });
    expect(options.account).toMatchObject({
      storeStateStrategy: 'cookie',
      storeAccountCookie: true,
      encryptOAuthTokens: true,
    });
    expect(options.advanced).toMatchObject({
      useSecureCookies: true,
      cookiePrefix: 'vetted',
      defaultCookieAttributes: {
        httpOnly: true,
        secure: true,
        sameSite: 'lax',
        path: '/',
      },
    });
    expect(options.advanced?.disableCSRFCheck).not.toBe(true);
    expect(options.advanced?.disableOriginCheck).not.toBe(true);
  });

  test('configures Cognito OIDC discovery, PKCE, explicit issuer, and server client secret', () => {
    expect(createCognitoProviderConfig(config, secrets)).toEqual({
      providerId: COGNITO_PROVIDER_ID,
      clientId: 'client-id',
      clientSecret: 'cognito-client-secret',
      discoveryUrl: config.cognitoDiscoveryUrl,
      issuer: config.cognitoIssuer,
      requireIssuerValidation: false,
      scopes: ['openid', 'email', 'profile'],
      pkce: true,
      authentication: 'basic',
      disableImplicitSignUp: false,
      disableSignUp: false,
    });
  });

  test('accepts only HTTPS origins plus explicit localhost development origins', () => {
    const environment = {
      BETTER_AUTH_URL: 'https://example.cloudfront.net',
      BETTER_AUTH_TRUSTED_ORIGINS:
        'https://example.cloudfront.net,http://127.0.0.1:5173,http://localhost:5173',
      COGNITO_ISSUER: config.cognitoIssuer,
      BETTER_AUTH_SECRET_ID: config.betterAuthSecretId,
      COGNITO_CLIENT_SECRET_ID: config.cognitoClientSecretId,
    };
    expect(readRuntimeConfig(environment)).toEqual(config);
    expect(() =>
      readRuntimeConfig({ ...environment, BETTER_AUTH_TRUSTED_ORIGINS: 'http://evil.example' }),
    ).toThrow(/must use HTTPS/);
    expect(() => readRuntimeConfig({ ...environment, BETTER_AUTH_URL: 'https://example.com/path' }))
      .toThrow(/must be an origin/);
  });
});
