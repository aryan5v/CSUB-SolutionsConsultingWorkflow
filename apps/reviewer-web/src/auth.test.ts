import { describe, expect, it, vi } from "vitest";
import { reviewerAuthenticationRequired } from "./AuthGate";
import {
  consumeOAuthResponse,
  createCognitoAuthProvider,
  localReviewerAuthBypassEnabled,
  type CognitoAuthConfig,
  type ReviewerAuthProvider,
} from "./auth";

const config: CognitoAuthConfig = {
  domain: "https://demo.auth.us-west-2.amazoncognito.com",
  clientId: "publicclient123",
  redirectUri: "https://review.example/app",
  logoutUri: "https://review.example/app",
};

function jwt(exp: number, claims: Record<string, unknown> = {}): string {
  const encode = (value: object) => btoa(JSON.stringify(value)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  return `${encode({ alg: "none" })}.${encode({ exp, ...claims })}.signature`;
}

function memoryStorage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
    removeItem: (key: string) => { values.delete(key); },
    values,
  };
}

function providerHarness(options: {
  now?: number;
  location?: { origin: string; pathname: string; search: string; hash: string };
  fetchImpl?: typeof fetch;
} = {}) {
  const storage = memoryStorage();
  const replaceState = vi.fn();
  const navigate = vi.fn();
  const location = options.location ?? { origin: "https://review.example", pathname: "/app", search: "", hash: "" };
  const provider = createCognitoAuthProvider(config, {
    location: location as Location,
    history: { replaceState },
    storage,
    fetchImpl: options.fetchImpl ?? vi.fn() as unknown as typeof fetch,
    cryptoImpl: crypto,
    navigate,
    now: () => options.now ?? Date.now(),
  });
  return { provider, storage, replaceState, navigate };
}

async function beginSignIn(harness: ReturnType<typeof providerHarness>) {
  await harness.provider.signIn();
  const authorizeUrl = new URL(harness.navigate.mock.calls[0][0]);
  return {
    state: authorizeUrl.searchParams.get("state")!,
    nonce: authorizeUrl.searchParams.get("nonce")!,
    verifier: harness.storage.values.get("csub.reviewer.oauth.verifier")!,
    authorizeUrl,
  };
}

describe("Cognito reviewer OAuth PKCE", () => {
  it("uses authorization code with S256 PKCE and never puts the verifier in the URL", async () => {
    const harness = providerHarness();
    const { verifier, authorizeUrl } = await beginSignIn(harness);

    expect(authorizeUrl.pathname).toBe("/oauth2/authorize");
    expect(authorizeUrl.searchParams.get("response_type")).toBe("code");
    expect(authorizeUrl.searchParams.get("code_challenge_method")).toBe("S256");
    expect(authorizeUrl.searchParams.get("code_verifier")).toBeNull();
    expect(authorizeUrl.toString()).not.toContain(verifier);
  });

  it("exchanges a cleaned callback for a session-scoped access token", async () => {
    const now = 1_800_000_000_000;
    const first = providerHarness({ now });
    const { state, nonce, verifier } = await beginSignIn(first);
    const storage = first.storage;
    const replaceState = vi.fn();
    const fetchImpl = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      access_token: jwt(now / 1000 + 3600),
      id_token: jwt(now / 1000 + 3600, { name: "Synthetic Reviewer", email: "synthetic-reviewer@example.invalid", nonce }),
      expires_in: 3600,
      refresh_token: "ignored-refresh-token",
      token_type: "Bearer",
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    storage.setItem("csub.reviewer.oauth.verifier", verifier);
    storage.setItem("csub.reviewer.oauth.state", state);
    storage.setItem("csub.reviewer.oauth.nonce", nonce);
    const provider = createCognitoAuthProvider(config, {
      location: { origin: "https://review.example", pathname: "/app", search: `?code=one-time-code&state=${state}&view=queue`, hash: "" } as Location,
      history: { replaceState }, storage, fetchImpl, cryptoImpl: crypto, navigate: vi.fn(), now: () => now,
    });

    await expect(provider.initialize()).resolves.toMatchObject({ status: "authenticated", name: "Synthetic Reviewer", email: "synthetic-reviewer@example.invalid" });
    expect(replaceState).toHaveBeenCalledWith(null, "", "/app?view=queue");
    const tokenRequest = fetchImpl.mock.calls[0][1];
    expect(String(tokenRequest.body)).toContain("code_verifier=");
    expect(String(tokenRequest.body)).not.toContain("ignored-refresh-token");
    expect(storage.values.get("csub.reviewer.oauth.session")).not.toContain("ignored-refresh-token");
  });

  it("clears expired sessions and reports expiry", async () => {
    const now = 1_800_000_000_000;
    const harness = providerHarness({ now });
    harness.storage.setItem("csub.reviewer.oauth.session", JSON.stringify({
      accessToken: jwt(now / 1000 - 1),
      expiresAt: now - 1000,
    }));

    await expect(harness.provider.initialize()).resolves.toMatchObject({ status: "signed_out" });
    expect(harness.provider.getAccessToken()).toBeNull();
    expect(harness.storage.values.has("csub.reviewer.oauth.session")).toBe(false);
  });

  it("clears session state and uses the configured Cognito logout URI", async () => {
    const harness = providerHarness();
    harness.storage.setItem("csub.reviewer.oauth.session", "sensitive-session-state");
    harness.provider.signOut();

    expect(harness.storage.values.has("csub.reviewer.oauth.session")).toBe(false);
    const logoutUrl = new URL(harness.navigate.mock.calls[0][0]);
    expect(logoutUrl.pathname).toBe("/logout");
    expect(logoutUrl.searchParams.get("client_id")).toBe(config.clientId);
    expect(logoutUrl.searchParams.get("logout_uri")).toBe(config.logoutUri);
  });

  it("rejects mismatched callback state before making a token request", async () => {
    const fetchImpl = vi.fn();
    const harness = providerHarness({
      location: { origin: "https://review.example", pathname: "/app", search: "?code=code&state=attacker", hash: "" },
      fetchImpl,
    });
    harness.storage.setItem("csub.reviewer.oauth.verifier", "verifier");
    harness.storage.setItem("csub.reviewer.oauth.state", "expected");

    await expect(harness.provider.initialize()).resolves.toMatchObject({ status: "error" });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("rejects and cleans an implicit-token callback", async () => {
    const harness = providerHarness({
      location: { origin: "https://review.example", pathname: "/app", search: "", hash: "#access_token=legacy-token&token_type=Bearer" },
    });

    await expect(harness.provider.initialize()).resolves.toMatchObject({ status: "error" });
    expect(harness.replaceState).toHaveBeenCalledWith(null, "", "/app");
    expect(harness.provider.getAccessToken()).toBeNull();
  });
});

describe("OAuth URL cleanup and fixture separation", () => {
  it("removes OAuth query and fragment values while preserving unrelated query state", () => {
    const replaceState = vi.fn();
    const response = consumeOAuthResponse(
      { pathname: "/app", search: "?view=queue&code=secret-code&state=state", hash: "#access_token=legacy-token" } as Location,
      { replaceState },
    );

    expect(response.code).toBe("secret-code");
    expect(response.implicitTokenReturned).toBe(true);
    expect(replaceState).toHaveBeenCalledWith(null, "", "/app?view=queue");
    expect(JSON.stringify(replaceState.mock.calls)).not.toContain("secret-code");
    expect(JSON.stringify(replaceState.mock.calls)).not.toContain("legacy-token");
  });

  it("requires authentication only in live mode", () => {
    expect(reviewerAuthenticationRequired("live")).toBe(true);
    expect(reviewerAuthenticationRequired("fixture")).toBe(false);
  });

  it("allows the explicit auth bypass only for a local development build", () => {
    expect(localReviewerAuthBypassEnabled({ DEV: true, VITE_LOCAL_AUTH_BYPASS: "true" }, "127.0.0.1")).toBe(true);
    expect(localReviewerAuthBypassEnabled({ DEV: false, VITE_LOCAL_AUTH_BYPASS: "true" }, "127.0.0.1")).toBe(false);
    expect(localReviewerAuthBypassEnabled({ DEV: true, VITE_LOCAL_AUTH_BYPASS: "true" }, "review.example.edu")).toBe(false);
  });

  it("lets an explicit fixture bypass avoid every auth-provider operation", () => {
    const provider: ReviewerAuthProvider = {
      initialize: vi.fn(), getSnapshot: vi.fn(), getAccessToken: vi.fn(), signIn: vi.fn(), signOut: vi.fn(), handleUnauthorized: vi.fn(), subscribe: vi.fn(),
    };
    if (reviewerAuthenticationRequired("fixture")) provider.initialize();
    expect(provider.initialize).not.toHaveBeenCalled();
  });
});
