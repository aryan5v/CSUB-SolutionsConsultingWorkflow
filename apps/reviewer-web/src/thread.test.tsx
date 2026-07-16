import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createReviewApiClient, type ReviewerThreadMessage } from "./api";
import { VendorThreadPanel } from "./PublicIntake";
import type { ReviewerAuthProvider } from "./auth";

function authProvider(token = "reviewer-jwt") {
  return {
    initialize: vi.fn(),
    getSnapshot: vi.fn().mockReturnValue({ status: "authenticated" }),
    getAccessToken: vi.fn().mockReturnValue(token),
    signIn: vi.fn(),
    signOut: vi.fn(),
    handleUnauthorized: vi.fn(),
    subscribe: vi.fn(),
  } satisfies ReviewerAuthProvider;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("clarification thread client (issue #41)", () => {
  it("posts a vendor message with the invite bearer token, not reviewer auth", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ message_id: "msg-1" }));
    const client = createReviewApiClient({ mode: "live", fetchImpl: fetchMock, authProvider: authProvider() });

    await client.postVendorMessage("invite-token", { category: "question", body: "Which VPAT?" });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/vendor/invites/current/thread");
    expect(init.method).toBe("POST");
    const headers = new Headers(init.headers);
    // Vendor calls carry the invite token, never a reviewer JWT.
    expect(headers.get("Authorization")).toBe("Bearer invite-token");
    expect(JSON.parse(init.body as string)).toEqual({
      category: "question",
      body: "Which VPAT?",
    });
  });

  it("sends a reviewer reply with reviewer identity in the body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ message_id: "msg-2" }));
    const client = createReviewApiClient({ mode: "live", fetchImpl: fetchMock, authProvider: authProvider() });

    await client.postCaseReply("CASE-1", {
      body: "SOC 2 Type II, please.",
      reviewerId: "reviewer@csub.edu",
      in_reply_to: "msg-1",
      resolve: true,
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/cases/CASE-1/thread");
    expect(JSON.parse(init.body as string)).toEqual({
      body: "SOC 2 Type II, please.",
      in_reply_to: "msg-1",
      resolve: true,
      reviewer_id: "reviewer@csub.edu",
    });
  });

  it("resolves a message through the case-scoped resolve route", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ message_id: "msg-1", resolved: true }));
    const client = createReviewApiClient({ mode: "live", fetchImpl: fetchMock, authProvider: authProvider() });

    await client.resolveCaseMessage("CASE-1", "msg-1", true);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/cases/CASE-1/thread/msg-1/resolve");
    expect(JSON.parse(init.body as string)).toEqual({ resolved: true });
  });
});

describe("VendorThreadPanel rendering (issue #41)", () => {
  it("renders vendor and reviewer messages as escaped text with role labels", async () => {
    const messages: ReviewerThreadMessage[] = [
      {
        message_id: "msg-1", case_id: "CASE-1", author_role: "vendor", category: "question",
        body: "<script>alert('x')</script>", created_at: "2026-07-15T10:00:00Z", requirement_id: null,
        submission_id: "sub-1", submission_version: 1, author_id: null, visibility: "public",
        resolved: false, read_by_reviewer: false, in_reply_to: null,
      },
      {
        message_id: "msg-2", case_id: "CASE-1", author_role: "reviewer", category: "reply",
        body: "Happy to help.", created_at: "2026-07-15T11:00:00Z", requirement_id: null,
        submission_id: null, submission_version: null, author_id: "reviewer@csub.edu",
        visibility: "public", resolved: false, read_by_reviewer: true, in_reply_to: "msg-1",
      },
    ];
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: messages }));
    vi.stubGlobal("fetch", fetchMock);

    // Server-render is enough to assert the untrusted body is HTML-escaped and
    // reviewer identity never appears in the vendor-facing panel.
    const html = renderToStaticMarkup(<VendorThreadPanel token="invite-token" />);

    expect(html).toContain("Ask the campus team");
    expect(html).not.toContain("<script>alert");
    expect(html).not.toContain("reviewer@csub.edu");
  });
});
