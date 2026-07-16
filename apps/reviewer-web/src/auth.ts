export type ReviewerAuthStatus = "checking" | "authenticated" | "signed_out" | "error";

export type ReviewerAuthSnapshot = {
  status: ReviewerAuthStatus;
  name?: string;
  email?: string;
  message?: string;
};

export interface ReviewerAuthProvider {
  initialize(): Promise<ReviewerAuthSnapshot>;
  getSnapshot(): ReviewerAuthSnapshot;
  getAccessToken(): string | null;
  signIn(): Promise<void>;
  signOut(): void;
  handleUnauthorized(): void;
  subscribe(listener: (snapshot: ReviewerAuthSnapshot) => void): () => void;
}

export type CognitoAuthConfig = {
  domain: string;
  clientId: string;
  redirectUri: string;
  logoutUri: string;
};

/**
 * Development escape hatch for the local reviewer demo. It is deliberately
 * ineffective in production builds and on non-loopback hosts.
 */
export function localReviewerAuthBypassEnabled(
  environment: Record<string, string | boolean | undefined> = import.meta.env,
  hostname = typeof window === "undefined" ? "" : window.location.hostname,
): boolean {
  return environment.DEV === true
    && environment.VITE_LOCAL_AUTH_BYPASS === "true"
    && (hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1");
}

type AuthLocation = Pick<Location, "origin" | "pathname" | "search" | "hash">;
type AuthHistory = Pick<History, "replaceState">;
type AuthStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

type AuthDependencies = {
  location: AuthLocation;
  history: AuthHistory;
  storage: AuthStorage;
  fetchImpl: typeof fetch;
  cryptoImpl: Crypto;
  navigate: (url: string) => void;
  now?: () => number;
};

type StoredSession = {
  accessToken: string;
  idToken?: string;
  expiresAt: number;
};

type OAuthResponse = {
  code: string | null;
  state: string | null;
  error: string | null;
  errorDescription: string | null;
  implicitTokenReturned: boolean;
};

const SESSION_KEY = "csub.reviewer.oauth.session";
const VERIFIER_KEY = "csub.reviewer.oauth.verifier";
const STATE_KEY = "csub.reviewer.oauth.state";
const NONCE_KEY = "csub.reviewer.oauth.nonce";
const OAUTH_KEYS = ["code", "state", "error", "error_description", "access_token", "id_token"];
const EXPIRY_SKEW_MS = 30_000;

function base64Url(bytes: Uint8Array): string {
  let binary = "";
  bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function randomValue(cryptoImpl: Crypto): string {
  return base64Url(cryptoImpl.getRandomValues(new Uint8Array(32)));
}

async function pkceChallenge(verifier: string, cryptoImpl: Crypto): Promise<string> {
  const digest = await cryptoImpl.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64Url(new Uint8Array(digest));
}

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  const payload = token.split(".")[1];
  if (!payload) return null;
  try {
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
    return JSON.parse(atob(padded)) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function safePublicUrl(value: string, label: string): URL {
  const url = new URL(value);
  const localDevelopment = url.hostname === "localhost" || url.hostname === "127.0.0.1";
  if ((url.protocol !== "https:" && !(localDevelopment && url.protocol === "http:")) || url.username || url.password) {
    throw new Error(`${label} must be HTTPS (HTTP is allowed only for localhost) and must not contain credentials.`);
  }
  return url;
}

function normalizeDomain(value: string): string {
  const url = safePublicUrl(value, "VITE_COGNITO_DOMAIN");
  if (url.search || url.hash || (url.pathname && url.pathname !== "/")) {
    throw new Error("VITE_COGNITO_DOMAIN must be the Cognito domain origin without a path, query, or fragment.");
  }
  return url.origin;
}

function oauthParameters(value: string, prefix: "?" | "#"): URLSearchParams {
  return new URLSearchParams(value.startsWith(prefix) ? value.slice(1) : value);
}

export function consumeOAuthResponse(
  location: Pick<Location, "pathname" | "search" | "hash">,
  history: AuthHistory,
): OAuthResponse {
  const query = oauthParameters(location.search, "?");
  const fragment = oauthParameters(location.hash, "#");
  const hasQueryResponse = OAUTH_KEYS.some((key) => query.has(key));
  const hasFragmentResponse = OAUTH_KEYS.some((key) => fragment.has(key));
  const source = hasQueryResponse ? query : fragment;
  const response = {
    code: source.get("code"),
    state: source.get("state"),
    error: source.get("error"),
    errorDescription: source.get("error_description"),
    implicitTokenReturned: query.has("access_token") || query.has("id_token") || fragment.has("access_token") || fragment.has("id_token"),
  };

  if (hasQueryResponse || hasFragmentResponse) {
    OAUTH_KEYS.forEach((key) => query.delete(key));
    const nextQuery = query.toString();
    const nextFragment = hasFragmentResponse ? "" : location.hash;
    history.replaceState(null, "", `${location.pathname}${nextQuery ? `?${nextQuery}` : ""}${nextFragment}`);
  }

  return response;
}

export function readCognitoAuthConfig(
  environment: Record<string, string | boolean | undefined>,
  origin: string,
): CognitoAuthConfig {
  const domain = String(environment.VITE_COGNITO_DOMAIN ?? "").trim();
  const clientId = String(environment.VITE_COGNITO_CLIENT_ID ?? "").trim();
  if (!domain || !clientId) {
    throw new Error("Live reviewer sign-in requires VITE_COGNITO_DOMAIN and VITE_COGNITO_CLIENT_ID.");
  }
  if (!/^[A-Za-z0-9]+$/.test(clientId)) throw new Error("VITE_COGNITO_CLIENT_ID is invalid.");
  const defaultAppUri = `${origin.replace(/\/$/, "")}/app`;
  const redirectUri = safePublicUrl(String(environment.VITE_COGNITO_REDIRECT_URI ?? defaultAppUri), "VITE_COGNITO_REDIRECT_URI").toString();
  const logoutUri = safePublicUrl(String(environment.VITE_COGNITO_LOGOUT_URI ?? defaultAppUri), "VITE_COGNITO_LOGOUT_URI").toString();
  return { domain: normalizeDomain(domain), clientId, redirectUri, logoutUri };
}

export function createCognitoAuthProvider(
  config: CognitoAuthConfig,
  dependencies: AuthDependencies,
): ReviewerAuthProvider {
  const now = dependencies.now ?? Date.now;
  const listeners = new Set<(snapshot: ReviewerAuthSnapshot) => void>();
  let snapshot: ReviewerAuthSnapshot = { status: "checking" };
  let session: StoredSession | null = null;
  let initialization: Promise<ReviewerAuthSnapshot> | null = null;

  const publish = (next: ReviewerAuthSnapshot) => {
    snapshot = next;
    listeners.forEach((listener) => listener(snapshot));
    return snapshot;
  };

  const clearSession = () => {
    session = null;
    dependencies.storage.removeItem(SESSION_KEY);
    dependencies.storage.removeItem(VERIFIER_KEY);
    dependencies.storage.removeItem(STATE_KEY);
    dependencies.storage.removeItem(NONCE_KEY);
  };

  const activeSession = (candidate: StoredSession | null): candidate is StoredSession => {
    if (!candidate || typeof candidate.accessToken !== "string" || typeof candidate.expiresAt !== "number") return false;
    const claims = decodeJwtPayload(candidate.accessToken);
    const jwtExpiry = typeof claims?.exp === "number" ? claims.exp * 1000 : 0;
    return jwtExpiry > now() + EXPIRY_SKEW_MS && candidate.expiresAt > now() + EXPIRY_SKEW_MS;
  };

  const authenticate = (candidate: StoredSession): ReviewerAuthSnapshot => {
    session = candidate;
    const identity = candidate.idToken ? decodeJwtPayload(candidate.idToken) : null;
    const email = typeof identity?.email === "string" ? identity.email : undefined;
    const name = typeof identity?.name === "string"
      ? identity.name
      : [identity?.given_name, identity?.family_name].filter((value): value is string => typeof value === "string").join(" ") || undefined;
    return publish({ status: "authenticated", name, email });
  };

  const initializeOnce = async (): Promise<ReviewerAuthSnapshot> => {
    const response = consumeOAuthResponse(dependencies.location, dependencies.history);
    if (response.implicitTokenReturned) {
      clearSession();
      return publish({ status: "error", message: "The identity provider returned an unsupported implicit token response. Authorization code with PKCE is required." });
    }
    if (response.error) {
      clearSession();
      const detail = response.errorDescription?.trim();
      return publish({ status: "error", message: detail ? `Reviewer sign-in failed: ${detail}` : "Reviewer sign-in was not completed." });
    }
    if (response.code) {
      const expectedState = dependencies.storage.getItem(STATE_KEY);
      const expectedNonce = dependencies.storage.getItem(NONCE_KEY);
      const verifier = dependencies.storage.getItem(VERIFIER_KEY);
      dependencies.storage.removeItem(STATE_KEY);
      dependencies.storage.removeItem(NONCE_KEY);
      dependencies.storage.removeItem(VERIFIER_KEY);
      if (!expectedState || !response.state || response.state !== expectedState || !expectedNonce || !verifier) {
        clearSession();
        return publish({ status: "error", message: "Reviewer sign-in could not be verified. Start a new sign-in." });
      }
      const body = new URLSearchParams({
        grant_type: "authorization_code",
        client_id: config.clientId,
        code: response.code,
        redirect_uri: config.redirectUri,
        code_verifier: verifier,
      });
      const tokenResponse = await dependencies.fetchImpl(`${config.domain}/oauth2/token`, {
        method: "POST",
        credentials: "omit",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body,
      });
      if (!tokenResponse.ok) {
        clearSession();
        return publish({ status: "error", message: "Reviewer sign-in could not establish a session. Start a new sign-in." });
      }
      const payload = await tokenResponse.json() as Record<string, unknown>;
      const accessToken = typeof payload.access_token === "string" ? payload.access_token : "";
      const idToken = typeof payload.id_token === "string" ? payload.id_token : undefined;
      const expiresIn = typeof payload.expires_in === "number" ? payload.expires_in : 0;
      const claims = decodeJwtPayload(accessToken);
      const identity = idToken ? decodeJwtPayload(idToken) : null;
      const jwtExpiresAt = typeof claims?.exp === "number" ? claims.exp * 1000 : 0;
      const expiresAt = Math.min(jwtExpiresAt, now() + expiresIn * 1000);
      const nextSession = { accessToken, idToken, expiresAt };
      if (!activeSession(nextSession) || identity?.nonce !== expectedNonce) {
        clearSession();
        return publish({ status: "error", message: "Reviewer sign-in returned an invalid or expired access token." });
      }
      dependencies.storage.setItem(SESSION_KEY, JSON.stringify(nextSession));
      return authenticate(nextSession);
    }

    const stored = dependencies.storage.getItem(SESSION_KEY);
    if (stored) {
      try {
        const candidate = JSON.parse(stored) as StoredSession;
        if (activeSession(candidate)) return authenticate(candidate);
      } catch {
        // Invalid session-scoped state is discarded below without exposing it.
      }
    }
    clearSession();
    return publish({ status: "signed_out" });
  };

  return {
    initialize() {
      initialization ??= initializeOnce().catch(() => {
        clearSession();
        return publish({ status: "error", message: "Reviewer sign-in could not be completed." });
      });
      return initialization;
    },
    getSnapshot: () => snapshot,
    getAccessToken() {
      if (!activeSession(session)) {
        if (session) {
          clearSession();
          publish({ status: "signed_out", message: "Your reviewer session expired. Sign in again." });
        }
        return null;
      }
      return session.accessToken;
    },
    async signIn() {
      clearSession();
      const verifier = randomValue(dependencies.cryptoImpl);
      const state = randomValue(dependencies.cryptoImpl);
      const nonce = randomValue(dependencies.cryptoImpl);
      const challenge = await pkceChallenge(verifier, dependencies.cryptoImpl);
      dependencies.storage.setItem(VERIFIER_KEY, verifier);
      dependencies.storage.setItem(STATE_KEY, state);
      dependencies.storage.setItem(NONCE_KEY, nonce);
      publish({ status: "checking" });
      const url = new URL(`${config.domain}/oauth2/authorize`);
      url.search = new URLSearchParams({
        response_type: "code",
        client_id: config.clientId,
        redirect_uri: config.redirectUri,
        scope: "openid email profile",
        state,
        nonce,
        code_challenge_method: "S256",
        code_challenge: challenge,
      }).toString();
      dependencies.navigate(url.toString());
    },
    signOut() {
      clearSession();
      publish({ status: "signed_out", message: "You signed out of the reviewer workspace." });
      const url = new URL(`${config.domain}/logout`);
      url.search = new URLSearchParams({ client_id: config.clientId, logout_uri: config.logoutUri }).toString();
      dependencies.navigate(url.toString());
    },
    handleUnauthorized() {
      clearSession();
      publish({ status: "signed_out", message: "Your reviewer session is no longer authorized. Sign in again." });
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

function createUnavailableProvider(message: string): ReviewerAuthProvider {
  const snapshot: ReviewerAuthSnapshot = { status: "error", message };
  return {
    initialize: async () => snapshot,
    getSnapshot: () => snapshot,
    getAccessToken: () => null,
    signIn: async () => undefined,
    signOut: () => undefined,
    handleUnauthorized: () => undefined,
    subscribe: () => () => undefined,
  };
}

function configuredReviewerAuth(): ReviewerAuthProvider {
  if (typeof window === "undefined") return createUnavailableProvider("Reviewer sign-in requires a browser session.");
  try {
    const config = readCognitoAuthConfig(import.meta.env, window.location.origin);
    return createCognitoAuthProvider(config, {
      location: window.location,
      history: window.history,
      storage: window.sessionStorage,
      fetchImpl: window.fetch.bind(window),
      cryptoImpl: window.crypto,
      navigate: (url) => window.location.assign(url),
    });
  } catch (error) {
    return createUnavailableProvider(error instanceof Error ? error.message : "Reviewer sign-in is not configured.");
  }
}

export const reviewerAuth = configuredReviewerAuth();
