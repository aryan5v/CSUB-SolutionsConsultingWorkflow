# VETTED auth API

This workspace is the server-side VETTED authentication/session layer. It runs
Better Auth 1.6 as a Node.js 22 Lambda behind the existing CloudFront
distribution at `/api/auth/*` and uses the existing Cognito user pool as a
generic OIDC provider.

## Runtime design

- Better Auth has no database, so OAuth state, provider account data, and the
  eight-hour session are encrypted in secure, HTTP-only, SameSite=Lax cookies.
  The session cookie cache uses JWE and can be invalidated globally by changing
  its configured version.
- The provider uses OIDC discovery, an explicit Cognito issuer, authorization
  code flow, PKCE, and a confidential server-only app client. Cognito does not
  include RFC 9207 `iss` in every authorization response, so Better Auth's
  strict `requireIssuerValidation` callback mode remains off; the configured
  discovery document and issuer still pin the provider/token issuer.
- CloudFront signs origin requests to an `AWS_IAM` Lambda Function URL. A
  viewer-request function copies the exact `*.cloudfront.net` viewer host to a
  private header; the Lambda rejects any other forwarded host. Trusted browser
  origins are that exact request origin plus `127.0.0.1`/`localhost` development.
- The VETTED session key and Cognito client ID/secret are fetched from
  KMS-encrypted Secrets Manager records at Lambda cold start. Secret values are
  never Lambda environment variables, stack outputs, logs, or source values.
- Every Lambda response is `no-store`; CloudFront also uses its disabled cache
  policy and forwards all cookies/OIDC query strings plus only required headers.

Cognito self-signup is enabled only for the sanitized demo. The VETTED
`/signup` UI initiates `POST /api/auth/sign-in/oauth2` with provider `cognito`
and `requestSignUp: true`. A completed signup creates a reviewer demo account
in the one seeded `csub-demo` workspace; this is not multi-tenant enrollment or
production authorization.

Reviewer API routes remain protected by the existing Cognito JWT authorizer.
The existing public Cognito client is intentionally retained as the narrow
transition path until the reviewer API consumes Better Auth-compatible tokens;
no reviewer route is made public by this service.

## Commands

```bash
npm ci
npm run typecheck
npm test
npm run build
```

`npm run build` produces `dist/index.mjs`; CDK packages only `dist/**` from this
workspace. Build the service before deploying `PlatformStack`.

## Operational limits

Database-free sessions cannot revoke one browser immediately. The maximum
window is eight hours; changing the cookie-cache version or rotating the Better
Auth secret invalidates all sessions. Secrets Manager or Cognito credential
rotation must complete before old credentials are removed. Better Auth's
in-memory rate limit is per warm Lambda environment, so an edge/WAF control is
required before production use.
