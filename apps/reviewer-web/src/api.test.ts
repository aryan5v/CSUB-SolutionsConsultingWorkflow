import { afterEach, describe, expect, it, vi } from "vitest";
import {
  INLINE_EVIDENCE_MAX_BYTES,
  ReviewApiError,
  consumeInviteTokenFromFragment,
  createReviewApiClient,
  decisionVersion,
  packetEditSection,
  checklistStatusLabel,
  checklistStatusSettled,
  packetToDraft,
  queueItemToSummary,
  requiresReviewerConfirmation,
  reviewStageLabel,
  secureCorrelationId,
  suppressResolvedQuestions,
  vendorInviteUrl,
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

describe("secure correlation identifiers", () => {
  it("uses getRandomValues to create a valid UUID when randomUUID is unavailable", () => {
    const getRandomValues = vi.fn((target: Uint8Array) => {
      target.set(Array.from({ length: 16 }, (_, index) => index));
      return target;
    });

    const identifier = secureCorrelationId({ getRandomValues });

    expect(identifier).toBe("00010203-0405-4607-8809-0a0b0c0d0e0f");
    expect(identifier).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(getRandomValues).toHaveBeenCalledTimes(1);
  });
});

describe("review API client", () => {
  it("omits reviewer authorization only when the caller explicitly enables the local bypass", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [] }));
    const provider = authProvider("");
    const client = createReviewApiClient({ mode: "live", fetchImpl: fetchMock, authProvider: provider, authBypass: true });

    await client.listQueue();

    const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Headers;
    expect(headers.has("Authorization")).toBe(false);
    expect(provider.getAccessToken).not.toHaveBeenCalled();
  });

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

  it("reads evidence policy criteria for the reviewer", async () => {
    const criteria = {
      criteria_version_id: "policy-criteria-csub-demo-000",
      version: 0,
      updated_at: "",
      updated_by: "system:default",
      pentest_max_age_days: 365,
      pci_attestation_max_age_days: null,
      coi_required_coverages: ["cyber"],
      evidence_expiry_days: 365,
      provisional: true,
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(criteria));
    const client = createReviewApiClient({ mode: "live", fetchImpl: fetchMock, authProvider: authProvider() });

    await expect(client.getPolicyCriteria()).resolves.toEqual(criteria);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/policy-criteria");
    expect((init.method ?? "GET")).toBe("GET");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer reviewer-jwt");
  });

  it("saves edited policy criteria with a PUT and reviewer bearer", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ version: 1 }));
    const client = createReviewApiClient({ mode: "live", fetchImpl: fetchMock, authProvider: authProvider() });

    await client.updatePolicyCriteria({
      pentest_max_age_days: 180,
      pci_attestation_max_age_days: null,
      coi_required_coverages: ["cyber", "privacy"],
      evidence_expiry_days: 400,
      provisional: false,
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/policy-criteria");
    expect(init.method).toBe("PUT");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer reviewer-jwt");
    const body = JSON.parse(String(init.body));
    expect(body.pentest_max_age_days).toBe(180);
    expect(body.pci_attestation_max_age_days).toBeNull();
    expect(body.provisional).toBe(false);
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
      reviewer_id: "reviewer@vetted.local",
      action: "approve",
      decided_at: "2026-07-14T20:30:00.000Z",
      comments: "Internal reviewer note",
      vendor_visible_comment: "Vendor-safe completion message",
      edits: [{ section_key: "committee_routing", body: "Reviewer edit" }],
    });
    await client.previewWriteback("TR-260714-014");
    await client.commitWriteback("TR-260714-014", 3);

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      confirmed_match_id: "approved-row-172",
      reviewer_id: "reviewer@vetted.local",
    });
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toMatchObject({
      case_id: "TR-260714-014",
      action: "approve",
      comments: "Internal reviewer note",
      vendor_visible_comment: "Vendor-safe completion message",
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

  it("sends vendor-visible next actions only as explicit decision fields", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      state: state(), queue_item: {}, audit_events: [], simulated: true,
    }));
    const client = createReviewApiClient({ mode: "live", fetchImpl: fetchMock, authProvider: authProvider() });

    await client.recordDecision("TR-260714-014", {
      decision_version: 1,
      reviewer_id: "reviewer@vetted.local",
      action: "request_info",
      decided_at: "2026-07-14T20:30:00.000Z",
      comments: "Internal note",
      vendor_visible_comment: "Please provide the requested update.",
      vendor_next_actions: ["Upload the current product-specific ACR."],
    });

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      case_id: "TR-260714-014",
      decision_version: 1,
      reviewer_id: "reviewer@vetted.local",
      action: "request_info",
      decided_at: "2026-07-14T20:30:00.000Z",
      comments: "Internal note",
      vendor_visible_comment: "Please provide the requested update.",
      vendor_next_actions: ["Upload the current product-specific ACR."],
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
            reviewer_id: "reviewer@vetted.local",
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
          { error: { code: "approval_required", message: "approval required", correlation_id: "request-43" } },
          403,
        ),
      ),
    });

    await expect(client.previewWriteback("TR-260714-014")).rejects.toEqual(
      expect.objectContaining<Partial<ReviewApiError>>({
        status: 403,
        code: "approval_required",
        message: "approval required",
        correlationId: "request-43",
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

  it("builds complete links with tokens only in the fragment", () => {
    const url = vendorInviteUrl("https://demo.example/", "opaque+/value");
    expect(url).toBe("https://demo.example/intake#token=opaque%2B%2Fvalue");
    expect(new URL(url).search).toBe("");
  });

  it("collapses duplicate issue clicks and calls the authenticated rotation endpoint", async () => {
    const issued = {
      invite: { workspace_id: "csub-demo", invite_id: "invite-1", case_id: "case-1", product_id: "product-1", contact_id: "contact-1", issued_at: "2026-07-15T00:00:00Z", expires_at: "2026-07-22T00:00:00Z", status: "issued", opened_at: null, revoked_at: null, submitted_at: null, replaced_invite_id: null },
      token: "opaque-token-value-with-at-least-32-characters",
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(issued));
    const client = createReviewApiClient({ baseUrl: "/api", mode: "live", fetchImpl: fetchMock, authProvider: authProvider() });

    const [first, duplicate] = await Promise.all([
      client.issueInvite("case-1", "contact-1"),
      client.issueInvite("case-1", "contact-1"),
    ]);
    expect(first).toEqual(duplicate);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await client.rotateInvite("invite-1");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/invites/invite-1/resend");
    expect(fetchMock.mock.calls[1][1].method).toBe("POST");
    expect(new Headers(fetchMock.mock.calls[1][1].headers).get("Authorization")).toBe("Bearer reviewer-jwt");
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

  it("fetches the vendor review status with the bearer token only", async () => {
    const status = {
      invite: { invite_id: "invite-1", case_id: "case-1", expires_at: "2026-07-20T00:00:00Z", status: "submitted" },
      vendor: { vendor_id: "vendor-1", name: "Vendor" },
      product: { product_id: "product-1", name: "Product" },
      submission_status: "finalized",
      intake_analysis_complete: true,
      review_stage: "changes_requested",
      outcome: null,
      vendor_visible_comment: "Please update the accessibility evidence.",
      next_actions: ["Upload the current product-specific ACR."],
      checklist: [
        { requirement_id: "A11Y.VPAT.001", question: "Provide a current VPAT.", expected_evidence: ["VPAT"], status: "received" },
        { requirement_id: "SEC.DATA.001", question: "Describe encryption controls.", expected_evidence: ["SOC 2"], status: "processing" },
        { requirement_id: "SEC.HECVAT.001", question: "Provide a HECVAT.", expected_evidence: ["HECVAT"], status: "outstanding" },
      ],
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(status));
    const reviewer = authProvider("must-not-leak");
    const client = createReviewApiClient({ baseUrl: "/api", mode: "live", fetchImpl: fetchMock, authProvider: reviewer });

    const resolved = await client.getReviewStatus("raw-secret-token");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/vendor/invites/current/status");
    expect(url).not.toContain("raw-secret-token");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer raw-secret-token");
    expect(reviewer.getAccessToken).not.toHaveBeenCalled();
    expect(resolved.checklist.map((item) => item.status)).toEqual(["received", "processing", "outstanding"]);
    // An unvalidated free-text answer is never presented as received evidence.
    expect(resolved.checklist.map((item) => checklistStatusLabel(item.status))).toEqual([
      "Received",
      "Processing",
      "Outstanding",
    ]);
    expect(checklistStatusSettled("received")).toBe(true);
    expect(checklistStatusSettled("accepted")).toBe(true);
    expect(checklistStatusSettled("processing")).toBe(false);
    expect(checklistStatusSettled("invalid")).toBe(false);
    expect(checklistStatusSettled("stale")).toBe(false);
    expect(checklistStatusLabel("invalid")).toBe("Needs attention");
    expect(checklistStatusLabel("stale")).toBe("Out of date");
    expect(resolved.vendor_visible_comment).toBe("Please update the accessibility evidence.");
    expect(resolved.next_actions).toEqual(["Upload the current product-specific ACR."]);
    expect(reviewStageLabel(resolved)).toBe("Changes requested");
    expect(reviewStageLabel({ review_stage: "under_review", outcome: null })).toBe("Under campus review");
    expect(reviewStageLabel({ review_stage: "decided", outcome: "approved" })).toBe("Review passed");
    expect(reviewStageLabel({ review_stage: "decided", outcome: "declined" })).toBe("Review did not pass");
    expect(reviewStageLabel({ review_stage: "changes_requested", outcome: null })).toBe("Changes requested");
  });

  it("polls current vendor evidence with the invite bearer and reviewer evidence with Cognito", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ items: [] })));
    const reviewer = authProvider("reviewer-jwt");
    const client = createReviewApiClient({ mode: "live", fetchImpl: fetchMock, authProvider: reviewer });

    await client.listEvidence("vendor-invite-token");
    await client.listCaseEvidence("case/one");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/vendor/invites/current/evidence");
    expect(new Headers(fetchMock.mock.calls[0][1].headers).get("Authorization")).toBe("Bearer vendor-invite-token");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/cases/case%2Fone/documents");
    expect(new Headers(fetchMock.mock.calls[1][1].headers).get("Authorization")).toBe("Bearer reviewer-jwt");
    expect(JSON.stringify(fetchMock.mock.calls)).not.toContain("claim_token");
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

describe("vendor contacts live CRUD", () => {
  it("lists contacts from the live /vendor-contacts endpoint", async () => {
    const contact = {
      workspace_id: "csub-demo",
      contact_id: "contact-1",
      vendor_id: "vendor-1",
      name: "Jordan Vendor",
      email: "jordan@vendor.example",
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [contact] }));
    const client = createReviewApiClient({ mode: "live", fetchImpl: fetchMock, authProvider: authProvider() });

    const contacts = await client.listContacts();

    expect(contacts).toEqual([contact]);
    expect(fetchMock).toHaveBeenCalledWith("/api/vendor-contacts", expect.any(Object));
  });

  it("scopes the live contact list by vendor id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [] }));
    const client = createReviewApiClient({ mode: "live", fetchImpl: fetchMock, authProvider: authProvider() });

    await client.listContacts("vendor-1");

    expect(fetchMock).toHaveBeenCalledWith("/api/vendor-contacts?vendor_id=vendor-1", expect.any(Object));
  });

  it("creates a contact with a POST to /vendor-contacts", async () => {
    const created = {
      workspace_id: "csub-demo",
      contact_id: "contact-2",
      vendor_id: "vendor-1",
      name: "Riley Vendor",
      email: "riley@vendor.example",
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(created));
    const client = createReviewApiClient({ mode: "live", fetchImpl: fetchMock, authProvider: authProvider() });

    const result = await client.createContact({ vendor_id: "vendor-1", name: "Riley Vendor", email: "riley@vendor.example" });

    expect(result).toEqual(created);
    expect(fetchMock).toHaveBeenCalledWith("/api/vendor-contacts", expect.objectContaining({ method: "POST" }));
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({ vendor_id: "vendor-1", name: "Riley Vendor", email: "riley@vendor.example" });
  });
});
