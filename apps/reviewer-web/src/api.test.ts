import { afterEach, describe, expect, it, vi } from "vitest";
import {
  INLINE_EVIDENCE_MAX_BYTES,
  ReviewApiError,
  consumeInviteTokenFromFragment,
  createReviewApiClient,
  decisionVersion,
  packetEditSection,
  packetToDraft,
  queueItemToSummary,
  requiresReviewerConfirmation,
  suppressResolvedQuestions,
  type QueueItem,
  type ReviewState,
  type VendorQuestion,
} from "./api";
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

function state(overrides: Partial<ReviewState> = {}): ReviewState {
  return {
    case_id: "TR-260714-014",
    status: "awaiting_review",
    workflow_version: "0.1.0",
    case_input: {
      product_name: "LabArchives",
      vendor_name: "LabArchives, LLC",
      requester: { name: "Sample Requester", email: "requester@example.edu" },
      use_case: "Sanitized pilot",
      expected_users: 120,
      platform: ["web"],
      data_classification: "internal",
      estimated_cost_usd: 8000,
      integrations: ["Canvas"],
      uses_sso: true,
      uses_ai: true,
      classroom_or_public_use: true,
    },
    software_candidates: [],
    confirmed_match_id: null,
    policy_result: null,
    specialist_results: {},
    draft_packet: null,
    human_edits: [],
    human_decision: null,
    write_preview: null,
    write_result: null,
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("review API client", () => {
  it("loads and maps review queue items", async () => {
    const item: QueueItem = {
      case_id: "TR-260714-014",
      product: "LabArchives",
      vendor: "LabArchives, LLC",
      requester: "College of Science",
      status: "Ready for review",
      route: "Pending route",
      match: "Fuzzy candidate",
      match_detail: "Approved export · Row 172",
      stage: "Match confirmation",
      updated: "Local API",
      owner: "Alex Reviewer",
      state: state({ status: "awaiting_match_confirmation" }),
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [item] }));
    const client = createReviewApiClient({ mode: "live", fetchImpl: fetchMock, authProvider: authProvider() });

    const items = await client.listQueue();

    expect(items).toEqual([item]);
    expect(queueItemToSummary(item)).toMatchObject({
      id: "TR-260714-014",
      route: "Pending route",
      matchDetail: "Approved export · Row 172",
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/review-queue", expect.any(Object));
    expect(new Headers(fetchMock.mock.calls[0][1].headers).get("Authorization")).toBe("Bearer reviewer-jwt");
  });

  it("fetches reviewer research by case without an invitation token", async () => {
    const payload = { case_id: "TR-260714-014", research_performed: false, research: null };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(payload));
    const client = createReviewApiClient({ mode: "live", fetchImpl: fetchMock, authProvider: authProvider() });

    await expect(client.getCaseResearch("TR-260714-014")).resolves.toEqual(payload);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/cases/TR-260714-014/research");
    expect(url).not.toContain("token");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer reviewer-jwt");
  });

  it("sends human confirmation, decision, preview, and explicit commit requests", async () => {
    const response = {
      state: state(),
      queue_item: {},
      audit_events: [],
      simulated: true,
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(response));
    const client = createReviewApiClient({ mode: "live", fetchImpl: fetchMock, authProvider: authProvider() });

    await client.analyzeCase("TR-260714-014", "approved-row-172");
    await client.recordDecision("TR-260714-014", {
      decision_version: 1,
      reviewer_id: "alex.reviewer@example.edu",
      action: "approve",
      decided_at: "2026-07-14T20:30:00.000Z",
      edits: [{ section_key: "committee_routing", body: "Reviewer edit" }],
    });
    await client.previewWriteback("TR-260714-014");
    await client.commitWriteback("TR-260714-014", 3);

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      confirmed_match_id: "approved-row-172",
      reviewer_id: "alex.reviewer@example.edu",
    });
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toMatchObject({
      case_id: "TR-260714-014",
      action: "approve",
      edits: [{ section_key: "committee_routing", body: "Reviewer edit" }],
    });
    expect(fetchMock.mock.calls[2][0]).toBe(
      "/api/cases/TR-260714-014/servicenow/preview",
    );
    expect(JSON.parse(fetchMock.mock.calls[3][1].body)).toEqual({
      second_confirmation: true,
      expected_version: 3,
    });
  });

  it("projects packets and increments versions after a recorded decision", () => {
    const packet = {
      packet_id: "packet-1",
      case_id: "TR-260714-014",
      packet_version: 2,
      packet_type: "medium_risk" as const,
      sections: [
        { key: "summary", title: "Summary", body: "Body", editable: true },
        { key: "routing", title: "Routing", body: "Committee", editable: true },
      ],
    };
    expect(packetToDraft(packet)).toBe("Body");
    expect(decisionVersion(state({ draft_packet: packet }))).toBe(2);
    expect(decisionVersion(state({ draft_packet: packet }), true)).toBe(3);
    expect(
      decisionVersion(
        state({
          draft_packet: packet,
          human_decision: {
            case_id: "TR-260714-014",
            decision_version: 2,
            reviewer_id: "alex.reviewer@example.edu",
            action: "approve",
          },
        }),
      ),
    ).toBe(3);
    const lowPacket = {
      ...packet,
      packet_type: "low_risk" as const,
      sections: [
        { key: "recommendation", title: "Recommendation", body: "Low recommendation", editable: true },
      ],
    };
    expect(packetEditSection(lowPacket)?.key).toBe("recommendation");
    expect(packetToDraft(lowPacket)).toBe("Low recommendation");
  });

  it("surfaces structured API failures", async () => {
    const client = createReviewApiClient({
      mode: "live",
      authProvider: authProvider(),
      fetchImpl: vi.fn().mockResolvedValue(
        jsonResponse(
          { error: { code: "approval_required", message: "approval required" } },
          403,
        ),
      ),
    });

    await expect(client.previewWriteback("TR-260714-014")).rejects.toEqual(
      expect.objectContaining<Partial<ReviewApiError>>({
        status: 403,
        code: "approval_required",
        message: "approval required",
      }),
    );
  });
});


describe("vendor invitation security", () => {
  it("consumes an opaque fragment token and removes it from visible history", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
    };
    const replaceState = vi.fn();
    const token = consumeInviteTokenFromFragment(
      { hash: "#token=opaque%2Bvalue", pathname: "/intake", search: "?source=email" } as Location,
      { replaceState } as unknown as History,
      storage,
    );

    expect(token).toBe("opaque+value");
    expect(replaceState).toHaveBeenCalledWith(null, "", "/intake?source=email");
    expect(
      consumeInviteTokenFromFragment(
        { hash: "", pathname: "/intake", search: "?source=email" } as Location,
        { replaceState } as unknown as History,
        storage,
      ),
    ).toBe("opaque+value");
  });

  it("uses a bearer header and never includes the raw token in the API path", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      invite: { invite_id: "invite-1", case_id: "case-1", expires_at: "2026-07-20T00:00:00Z", status: "opened" },
      vendor: { vendor_id: "vendor-1", name: "Vendor" },
      product: { product_id: "product-1", name: "Product" },
      contact: { contact_id: "contact-1", name: "Contact", email: "contact@example.com" },
      submission: { workspace_id: "csub-demo", submission_id: "submission-1", invite_id: "invite-1", case_id: "case-1", product_id: "product-1", version: 1, status: "draft", trust_center_url: null, answers: {}, evidence_artifact_ids: [], coverage_ids: [], updated_at: null, finalized_at: null },
      questions: [],
    }));
    const reviewer = authProvider("must-not-leak");
    const client = createReviewApiClient({ baseUrl: "/api", mode: "live", fetchImpl: fetchMock, authProvider: reviewer });

    await client.resolveInvite("raw-secret-token");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/vendor/invites/current");
    expect(url).not.toContain("raw-secret-token");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer raw-secret-token");
    expect(reviewer.getAccessToken).not.toHaveBeenCalled();
  });

  it("inlines small evidence bytes so the API can store and validate them", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({
      workspace_id: "csub-demo", artifact_id: "artifact-1", submission_id: "submission-1",
      filename: "evidence.txt", content_type: "text/plain", size_bytes: 8, sha256: "hash", untrusted: true,
    }));
    const client = createReviewApiClient({ mode: "live", fetchImpl: fetchMock, authProvider: authProvider() });

    const result = await client.uploadEvidence("vendor-invite-token", new File(["evidence"], "evidence.txt", { type: "text/plain" }));

    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(body.content_base64).toBe(btoa("evidence"));
    expect(result.transfer).toBe("uploaded");
    expect(result.notice).toBeUndefined();
  });

  it("registers files above 700 KB as manual-review metadata without inline bytes", async () => {
    const size = INLINE_EVIDENCE_MAX_BYTES + 1;
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({
      workspace_id: "csub-demo", artifact_id: "artifact-large", submission_id: "submission-1",
      filename: "coi-large.pdf", content_type: "application/pdf", size_bytes: size, sha256: "hash", untrusted: true,
    }));
    const client = createReviewApiClient({ mode: "live", fetchImpl: fetchMock, authProvider: authProvider() });

    const result = await client.uploadEvidence(
      "vendor-invite-token",
      new File([new Uint8Array(size)], "coi-large.pdf", { type: "application/pdf" }),
    );

    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(body.size_bytes).toBe(size);
    expect(body).not.toHaveProperty("content_base64");
    expect(result.transfer).toBe("simulated");
    expect(result.notice).toContain("requires manual review");
    expect(result.notice).toContain("cannot automatically cover");
  });

  it("never attaches the reviewer JWT to a presigned evidence upload", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({
        workspace_id: "csub-demo", artifact_id: "artifact-1", submission_id: "submission-1",
        filename: "evidence.txt", content_type: "text/plain", size_bytes: 8, sha256: "hash", untrusted: true,
        upload: { url: "https://uploads.example/object", method: "PUT", headers: { Authorization: "Bearer server-supplied-value", "x-amz-meta-test": "safe" } },
      }))
      .mockResolvedValueOnce(new Response(null, { status: 200 }));
    const reviewer = authProvider("reviewer-jwt-must-not-leak");
    const client = createReviewApiClient({ mode: "live", fetchImpl: fetchMock, authProvider: reviewer });

    await client.uploadEvidence("vendor-invite-token", new File(["evidence"], "evidence.txt", { type: "text/plain" }));

    expect(new Headers(fetchMock.mock.calls[0][1].headers).get("Authorization")).toBe("Bearer vendor-invite-token");
    expect(new Headers(fetchMock.mock.calls[1][1].headers).get("Authorization")).toBeNull();
    expect(JSON.stringify(fetchMock.mock.calls[1])).not.toContain("reviewer-jwt-must-not-leak");
    expect(reviewer.getAccessToken).not.toHaveBeenCalled();
  });
});

describe("live and adaptive behavior", () => {
  it("surfaces a live transport failure without falling back to fixtures", async () => {
    const failure = new TypeError("network unavailable");
    const client = createReviewApiClient({ mode: "live", fetchImpl: vi.fn().mockRejectedValue(failure), authProvider: authProvider() });

    await expect(client.listVendors()).rejects.toBe(failure);
  });

  it("suppresses questions already answered or covered by evidence", () => {
    const questions: VendorQuestion[] = [
      { requirement_id: "SEC.1", question: "Security?", expected_evidence: ["SOC 2"] },
      { requirement_id: "A11Y.1", question: "Accessibility?", expected_evidence: ["VPAT"] },
      { requirement_id: "PRIV.1", question: "Privacy?", expected_evidence: ["Policy"] },
    ];

    expect(suppressResolvedQuestions(questions, { "SEC.1": "Saved answer" }, new Set(["A11Y.1"]))).toEqual([questions[2]]);
  });

  it("requires explicit confirmation for fuzzy and semantic matches only", async () => {
    expect(requiresReviewerConfirmation({ match_method: "fuzzy", requires_human_confirmation: true })).toBe(true);
    expect(requiresReviewerConfirmation({ match_method: "semantic", requires_human_confirmation: true })).toBe(true);
    expect(requiresReviewerConfirmation({ match_method: "exact", requires_human_confirmation: false })).toBe(false);

    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ confirmed: true, approval_granted: false }));
    const client = createReviewApiClient({ baseUrl: "/api", mode: "live", fetchImpl: fetchMock, authProvider: authProvider() });
    await client.confirmCatalogMatch("row-17", "fuzzy", "reviewer@example.edu");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/catalog/matches/row-17/confirm");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ match_method: "fuzzy", reviewer_id: "reviewer@example.edu" });
  });

  it("clears reviewer auth on 401 but preserves structured 403 behavior", async () => {
    const reviewer = authProvider();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ error: { code: "unauthorized", message: "expired" } }, 401))
      .mockResolvedValueOnce(jsonResponse({ error: { code: "forbidden", message: "not allowed" } }, 403));
    const client = createReviewApiClient({ mode: "live", fetchImpl: fetchMock, authProvider: reviewer });

    await expect(client.listVendors()).rejects.toMatchObject({ status: 401 });
    expect(reviewer.handleUnauthorized).toHaveBeenCalledTimes(1);
    await expect(client.listVendors()).rejects.toMatchObject({ status: 403 });
    expect(reviewer.handleUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("keeps explicit fixture mode isolated from auth and network", async () => {
    const reviewer = authProvider();
    const fetchMock = vi.fn();
    const client = createReviewApiClient({ mode: "fixture", fetchImpl: fetchMock, authProvider: reviewer });

    await expect(client.listVendors()).resolves.toHaveLength(1);
    await expect(client.getCaseResearch("fixture-case")).resolves.toEqual({
      case_id: "fixture-case",
      research_performed: false,
      research: null,
    });
    await expect(client.analyzeCase("fixture-case")).rejects.toMatchObject({ code: "fixture_network_blocked" });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(reviewer.getAccessToken).not.toHaveBeenCalled();
  });
});
