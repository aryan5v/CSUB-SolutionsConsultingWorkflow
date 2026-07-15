import { describe, expect, it, vi } from "vitest";
import {
  createAuthClient,
  createBetterAuthReviewerProvider,
  type AuthClient,
  type BetterAuthReactClientLike,
} from "./authClient";

function rawClient(overrides: Partial<BetterAuthReactClientLike> = {}): BetterAuthReactClientLike {
  return {
    getSession: vi.fn().mockResolvedValue({ data: { user: { id: "u1", email: "reviewer@example.edu" }, session: { token: "better-auth-session" } } }),
    getAccessToken: vi.fn().mockResolvedValue({ data: { accessToken: "cognito-access-token" } }),
    signIn: { oauth2: vi.fn().mockResolvedValue({ data: { url: "https://cognito.example/authorize", redirect: true } }) },
    signOut: vi.fn().mockResolvedValue({ data: { success: true } }),
    ...overrides,
  };
}

describe("Better Auth OIDC adapter", () => {
  it("sign-in calls generic OAuth for cognito without requestSignUp and redirects to the returned url", async () => {
    const raw = rawClient();
    const navigate = vi.fn();
    const client = createAuthClient({ rawClient: raw, navigate, oauthProvider: "cognito", origin: "https://vetted.example" });

    const result = await client.signInWithCognito();

    expect(result.ok).toBe(true);
    expect(raw.signIn.oauth2).toHaveBeenCalledWith({ providerId: "cognito", callbackURL: "https://vetted.example/app" });
    expect(navigate).toHaveBeenCalledWith("https://cognito.example/authorize");
  });

  it("sign-up passes requestSignUp true so Cognito opens account creation", async () => {
    const raw = rawClient();
    const client = createAuthClient({ rawClient: raw, navigate: vi.fn(), oauthProvider: "cognito", origin: "https://vetted.example" });

    await client.signInWithCognito({ requestSignUp: true });

    expect(raw.signIn.oauth2).toHaveBeenCalledWith({ providerId: "cognito", callbackURL: "https://vetted.example/app", requestSignUp: true });
  });

  it("surfaces a plain-language error and does not navigate on OAuth failure", async () => {
    const raw = rawClient({ signIn: { oauth2: vi.fn().mockResolvedValue({ error: { code: "PROVIDER_NOT_FOUND", status: 404 } }) } });
    const navigate = vi.fn();
    const client = createAuthClient({ rawClient: raw, navigate });

    const result = await client.signInWithCognito();

    expect(result.ok).toBe(false);
    expect(result.error?.message).toContain("Campus single sign-on is not configured");
    expect(navigate).not.toHaveBeenCalled();
  });

  it("retrieves the Cognito provider access token through the official client", async () => {
    const raw = rawClient();
    const client = createAuthClient({ rawClient: raw, navigate: vi.fn(), oauthProvider: "cognito" });

    const result = await client.getProviderAccessToken();

    expect(raw.getAccessToken).toHaveBeenCalledWith({ providerId: "cognito" });
    expect(result.data?.accessToken).toBe("cognito-access-token");
  });
});

function adapterStub(overrides: Partial<AuthClient> = {}): AuthClient {
  return {
    baseURL: "https://vetted.example/api/auth",
    getSession: vi.fn().mockResolvedValue({ ok: true, status: 200, data: { user: { email: "reviewer@example.edu" }, session: { token: "session-token" } } }),
    getProviderAccessToken: vi.fn().mockResolvedValue({ ok: true, status: 200, data: { accessToken: "cognito-access-token" } }),
    signInWithCognito: vi.fn(),
    signOut: vi.fn().mockResolvedValue({ ok: true, status: 200 }),
    ...overrides,
  } as unknown as AuthClient;
}

describe("Better Auth reviewer provider", () => {
  it("returns the Cognito access token as the bearer after initialize", async () => {
    const client = adapterStub();
    const provider = createBetterAuthReviewerProvider({ client, navigate: vi.fn() });

    const snapshot = await provider.initialize();

    expect(snapshot).toMatchObject({ status: "authenticated", email: "reviewer@example.edu" });
    expect(provider.getAccessToken()).toBe("cognito-access-token");
  });

  it("errors and keeps the token null when the Cognito token cannot be retrieved (never falls back to the session token)", async () => {
    const client = adapterStub({
      getProviderAccessToken: vi.fn().mockResolvedValue({ ok: false, status: 400, error: { message: "no linked account" } }),
    });
    const provider = createBetterAuthReviewerProvider({ client, navigate: vi.fn() });

    const snapshot = await provider.initialize();

    expect(snapshot.status).toBe("error");
    expect(provider.getAccessToken()).toBeNull();
  });

  it("reports signed_out when there is no session user", async () => {
    const client = adapterStub({ getSession: vi.fn().mockResolvedValue({ ok: true, status: 200, data: {} }) });
    const provider = createBetterAuthReviewerProvider({ client, navigate: vi.fn() });

    await expect(provider.initialize()).resolves.toMatchObject({ status: "signed_out" });
    expect(provider.getAccessToken()).toBeNull();
  });

  it("signIn navigates to the dedicated /login surface", async () => {
    const navigate = vi.fn();
    const provider = createBetterAuthReviewerProvider({ client: adapterStub(), navigate });
    await provider.signIn();
    expect(navigate).toHaveBeenCalledWith("/login");
  });
});
