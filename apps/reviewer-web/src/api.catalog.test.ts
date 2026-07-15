import { describe, expect, it, vi } from "vitest";
import { createReviewApiClient } from "./api";
import type { ReviewerAuthProvider } from "./auth";

function authProvider(token = "cognito-access-token"): ReviewerAuthProvider {
  return {
    initialize: vi.fn(),
    getSnapshot: vi.fn().mockReturnValue({ status: "authenticated" }),
    getAccessToken: vi.fn().mockReturnValue(token),
    signIn: vi.fn(),
    signOut: vi.fn(),
    handleUnauthorized: vi.fn(),
    subscribe: vi.fn(),
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("catalog browser client", () => {
  it("requests protected GET /catalog with q/limit/offset and returns the contract shape", async () => {
    const payload = { items: [{ record_id: "row-238", canonical_name: "Canvas", vendor: "Instructure", support_flag: "Supported", license_flag: "Institution license", source_row: 238 }], total: 1, limit: 20, offset: 0, catalog_membership_is_approval: false as const };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(payload));
    const client = createReviewApiClient({ mode: "live", fetchImpl: fetchMock, authProvider: authProvider() });

    const result = await client.listCatalog("canvas", 20, 0);

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toBe("/api/catalog?limit=20&offset=0&q=canvas");
    expect(new Headers(fetchMock.mock.calls[0][1].headers).get("Authorization")).toBe("Bearer cognito-access-token");
    expect(result.items[0]).toMatchObject({ canonical_name: "Canvas", vendor: "Instructure", support_flag: "Supported" });
    expect(result.total).toBe(1);
    expect(result.catalog_membership_is_approval).toBe(false);
  });

  it("normalizes a records-shaped catalog payload and never implies approval", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ records: [{ record_id: "r1", canonical_name: "Zoom", vendor: "Zoom" }] }));
    const client = createReviewApiClient({ mode: "live", fetchImpl: fetchMock, authProvider: authProvider() });

    const result = await client.listCatalog();

    expect(result.items).toHaveLength(1);
    expect(result.catalog_membership_is_approval).toBe(false);
  });

  it("returns fixture catalog rows without touching the network", async () => {
    const fetchMock = vi.fn();
    const client = createReviewApiClient({ mode: "fixture", fetchImpl: fetchMock, authProvider: authProvider() });

    const result = await client.listCatalog("qualtrics");

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.items.every((row) => `${row.canonical_name}`.toLowerCase().includes("qualtrics"))).toBe(true);
    expect(result.catalog_membership_is_approval).toBe(false);
  });
});

describe("one custom rerun", () => {
  it("posts a single custom-instruction rerun to the analyze endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ state: {}, queue_item: {}, audit_events: [], simulated: true }));
    const client = createReviewApiClient({ mode: "live", fetchImpl: fetchMock, authProvider: authProvider() });

    await client.rerunAnalysis("TR-260714-014", "recheck the VPAT against the requested version");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/cases/TR-260714-014/analyze");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      reviewer_id: "alex.reviewer@example.edu",
      rerun: true,
      custom_instruction: "recheck the VPAT against the requested version",
    });
  });
});

describe("packet PDF access", () => {
  it("fetches packet PDF metadata through the authenticated request, not a naked URL", async () => {
    const meta = { view_url: "https://files.example/packet.pdf", content_type: "application/pdf", size_bytes: 8192, pdf_sha256: "abc123" };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(meta));
    const client = createReviewApiClient({ mode: "live", fetchImpl: fetchMock, authProvider: authProvider() });

    const result = await client.getPacketPdf("TR-260714-014");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/cases/TR-260714-014/packet/pdf");
    expect(url).not.toContain("cognito-access-token");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer cognito-access-token");
    expect(result.view_url).toBe("https://files.example/packet.pdf");
  });

  it("returns truthful simulated metadata in fixture mode without a view url", async () => {
    const fetchMock = vi.fn();
    const client = createReviewApiClient({ mode: "fixture", fetchImpl: fetchMock, authProvider: authProvider() });

    const result = await client.getPacketPdf("FIXTURE-CASE");

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.simulated).toBe(true);
    expect(result.view_url).toBeNull();
  });
});
