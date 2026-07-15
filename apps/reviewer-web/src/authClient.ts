import { createAuthClient as createBetterAuthReactClient } from "better-auth/react";
import { genericOAuthClient } from "better-auth/client/plugins";
import type { ReviewerAuthProvider, ReviewerAuthSnapshot } from "./auth";

/*
 * Better Auth integration for the reviewer workspace. The official
 * `better-auth/react` client owns the transport, session store, and cookie
 * handling; it talks only to the Better Auth server mounted at `/api/auth`.
 *
 * The auth server is stateless and OIDC only: it does not enable Better Auth
 * email/password. Sign-in and account creation both run through Better Auth
 * generic OAuth (`signIn.oauth2`) against the campus Cognito provider. Account
 * creation passes `requestSignUp: true` so Cognito opens its sign-up screen.
 *
 * A small adapter wraps the official client so the UI has a stable, testable
 * surface with normalized, plain-language errors, and so the existing
 * bearer-based reviewer API keeps working through `ReviewerAuthProvider`.
 */

export type AuthUser = { id?: string; email?: string; name?: string };
export type AuthSession = { token?: string; expiresAt?: string };
export type SessionResponse = { user?: AuthUser; session?: AuthSession } | null;

export type AuthResult<T = unknown> = {
  ok: boolean;
  status: number;
  data?: T;
  error?: { message: string; code?: string };
};

export type CognitoSignIn = { requestSignUp?: boolean; callbackURL?: string };

type RawError = { message?: string; code?: string; status?: number; statusText?: string } | null | undefined;
type RawResult<T = unknown> = { data?: T; error?: RawError };
type RedirectData = { url?: string; redirect?: boolean };

/**
 * Minimal structural view of the official Better Auth react client with the
 * generic OAuth plugin. Declaring only what the adapter uses keeps the wrapper
 * thin and lets tests inject a fake.
 */
export interface BetterAuthReactClientLike {
  getSession: (options?: unknown) => Promise<RawResult<SessionResponse>>;
  getAccessToken?: (input: { providerId: string; accountId?: string; userId?: string }) => Promise<RawResult<{ accessToken?: string; accessTokenExpiresAt?: string }>>;
  signIn: {
    oauth2: (input: { providerId: string; callbackURL?: string; requestSignUp?: boolean }) => Promise<RawResult<RedirectData>>;
  };
  signOut: () => Promise<RawResult>;
}

const FRIENDLY_ERRORS: Record<string, string> = {
  PROVIDER_NOT_FOUND: "Campus single sign-on is not configured for this workspace yet.",
  INVALID_OAUTH_CONFIGURATION: "Campus single sign-on is misconfigured. Contact the demo operator.",
};

function friendly(error: RawError, fallback: string): { message: string; code?: string } {
  const code = error?.code;
  if (code && FRIENDLY_ERRORS[code]) return { message: FRIENDLY_ERRORS[code], code };
  if (error?.status === 0 || error?.message === "Failed to fetch") {
    return { message: "The sign-in service could not be reached. Check your connection and try again.", code };
  }
  return { message: error?.message ?? fallback, code };
}

function normalize<T>(result: RawResult<T>, fallback: string): AuthResult<T> {
  if (result.error) {
    return { ok: false, status: result.error.status ?? 0, error: friendly(result.error, fallback) };
  }
  return { ok: true, status: 200, data: result.data };
}

export type AuthClientOptions = {
  baseURL?: string;
  basePath?: string;
  oauthProvider?: string;
  rawClient?: BetterAuthReactClientLike;
  navigate?: (url: string) => void;
  origin?: string;
};

export function createAuthClient(options: AuthClientOptions = {}) {
  const origin = options.origin ?? (typeof window !== "undefined" ? window.location.origin : "http://localhost");
  const baseURL = options.baseURL ?? origin;
  const basePath = options.basePath ?? "/api/auth";
  const oauthProvider = options.oauthProvider ?? "cognito";
  const navigate = options.navigate ?? ((url: string) => { if (typeof window !== "undefined") window.location.assign(url); });
  const client: BetterAuthReactClientLike =
    options.rawClient ??
    (createBetterAuthReactClient({ baseURL, basePath, plugins: [genericOAuthClient()] }) as unknown as BetterAuthReactClientLike);

  const appCallback = `${origin.replace(/\/$/, "")}/app`;

  return {
    baseURL: `${baseURL.replace(/\/$/, "")}${basePath}`,
    async getSession(): Promise<AuthResult<SessionResponse>> {
      return normalize<SessionResponse>(await client.getSession(), "Your session could not be verified.");
    },
    async getProviderAccessToken(): Promise<AuthResult<{ accessToken?: string }>> {
      if (!client.getAccessToken) return { ok: false, status: 0, error: { message: "Provider access token retrieval is not available." } };
      return normalize(await client.getAccessToken({ providerId: oauthProvider }), "Could not retrieve the campus access token.");
    },
    async signInWithCognito(input: CognitoSignIn = {}): Promise<AuthResult<RedirectData>> {
      const raw = await client.signIn.oauth2({
        providerId: oauthProvider,
        callbackURL: input.callbackURL ?? appCallback,
        ...(input.requestSignUp ? { requestSignUp: true } : {}),
      });
      const result = normalize(raw, "Campus single sign-on is not available right now. Try again in a moment.");
      if (result.ok && result.data?.url) navigate(result.data.url);
      return result;
    },
    async signOut(): Promise<AuthResult> {
      return normalize(await client.signOut(), "Sign-out did not complete.");
    },
  };
}

export type AuthClient = ReturnType<typeof createAuthClient>;

type ProviderDependencies = {
  client?: AuthClient;
  navigate?: (url: string) => void;
};

/**
 * Adapts the Better Auth client to the reviewer `ReviewerAuthProvider` used by
 * the API client and `AuthGate`. The reviewer API Gateway validates Cognito
 * JWTs, so `getAccessToken` returns the Cognito provider access token obtained
 * through Better Auth generic OAuth. If that token cannot be retrieved the
 * provider reports an auth error and keeps the token null; it never falls back
 * to the Better Auth session token, which the API Gateway would reject.
 */
export function createBetterAuthReviewerProvider(dependencies: ProviderDependencies = {}): ReviewerAuthProvider {
  const client = dependencies.client ?? createAuthClient();
  const navigate = dependencies.navigate ?? ((url: string) => { if (typeof window !== "undefined") window.location.assign(url); });
  const listeners = new Set<(snapshot: ReviewerAuthSnapshot) => void>();
  let snapshot: ReviewerAuthSnapshot = { status: "checking" };
  let token: string | null = null;
  let initialization: Promise<ReviewerAuthSnapshot> | null = null;

  const publish = (next: ReviewerAuthSnapshot) => {
    snapshot = next;
    listeners.forEach((listener) => listener(snapshot));
    return snapshot;
  };

  const load = async (): Promise<ReviewerAuthSnapshot> => {
    const result = await client.getSession();
    if (!result.ok) {
      token = null;
      if (result.status === 0) return publish({ status: "error", message: result.error?.message });
      return publish({ status: "signed_out" });
    }
    const user = result.data?.user;
    if (!user) {
      token = null;
      return publish({ status: "signed_out" });
    }
    const provided = await client.getProviderAccessToken();
    if (!provided.ok || !provided.data?.accessToken) {
      token = null;
      return publish({ status: "error", message: provided.error?.message ?? "Your campus access token could not be retrieved. Sign in again." });
    }
    token = provided.data.accessToken;
    return publish({ status: "authenticated", email: user.email });
  };

  return {
    initialize() {
      initialization ??= load().catch(() => publish({ status: "error", message: "Reviewer sign-in could not be verified." }));
      return initialization;
    },
    getSnapshot: () => snapshot,
    getAccessToken: () => token,
    async signIn() {
      navigate("/login");
    },
    signOut() {
      token = null;
      publish({ status: "signed_out", message: "You signed out of the reviewer workspace." });
      void client.signOut().finally(() => navigate("/"));
    },
    handleUnauthorized() {
      token = null;
      publish({ status: "signed_out", message: "Your reviewer session is no longer authorized. Sign in again." });
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

function configuredAuthClient(): AuthClient {
  if (typeof window === "undefined") return createAuthClient({ origin: "http://localhost" });
  return createAuthClient({ baseURL: window.location.origin, basePath: "/api/auth" });
}

export const authClient = configuredAuthClient();
export const betterAuthReviewer = createBetterAuthReviewerProvider({ client: authClient });
