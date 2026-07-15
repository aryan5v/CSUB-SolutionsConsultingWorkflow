import { reviewerAuth, type ReviewerAuthProvider } from "./auth";

export type QueueStatus = "Ready for review" | "Analyzing" | "Needs evidence" | "Completed";
export type RiskRoute = "Low risk" | "Medium risk" | "Safe escalation" | "Pending route";
export type ApiMode = "live" | "fixture";
export type MatchMethod = "exact" | "alias" | "vendor_product" | "fuzzy" | "semantic";

export type ReviewSummary = {
  id: string;
  product: string;
  vendor: string;
  requester: string;
  status: QueueStatus;
  route: RiskRoute;
  match: string;
  matchDetail: string;
  stage: string;
  updated: string;
  owner: string;
};

export type SourceCoordinates = {
  source_id: string;
  filename?: string | null;
  sheet?: string | null;
  row?: number | null;
  page?: number | null;
  cell?: string | null;
  section?: string | null;
};

export type SoftwareCandidate = {
  record_id: string;
  canonical_name?: string | null;
  match_method: MatchMethod;
  score: number;
  requires_confirmation: boolean;
  source_row_ref: SourceCoordinates;
};

export type CatalogCandidate = {
  record_id: string;
  canonical_name: string;
  vendor: string;
  source_row: number;
  match_method: MatchMethod;
  score: number;
  requires_human_confirmation: boolean;
  support_flag?: string | null;
  license_flag?: string | null;
};

export type PacketSection = { key: string; title: string; body: string; editable: boolean };
export type Packet = {
  packet_id: string;
  case_id: string;
  packet_version: number;
  packet_type: "low_risk" | "medium_risk";
  sections: PacketSection[];
  sha256?: string;
};

export type WritePreview = {
  case_id: string;
  decision_version: number;
  table: string;
  record_id: string;
  expected_record_version: number;
  packet_version: number;
  packet_sha256: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  field_changes: Array<{ field: string; from: unknown; to: unknown }>;
  simulated: true;
};

export type ReviewState = {
  case_id: string;
  status: string;
  workflow_version: string;
  case_input: {
    product_name: string;
    vendor_name: string;
    requester: { name: string; email: string; department?: string | null };
    use_case: string;
    expected_users: number;
    platform: string[];
    data_classification: string;
    estimated_cost_usd: number;
    integrations: string[];
    uses_sso: boolean;
    uses_ai: boolean;
    accessibility_context?: string | null;
    official_domain?: string | null;
    classroom_or_public_use: boolean;
  };
  software_candidates: SoftwareCandidate[];
  confirmed_match_id: string | null;
  policy_result: null | {
    policy_version: string;
    risk_route: "approved" | "low" | "medium" | "high" | "escalate" | "unknown";
    required_evidence: string[];
    escalated: boolean;
    escalation_reasons: string[];
    citations: Array<{ claim: string; source: SourceCoordinates; scope: string; verified: boolean }>;
  };
  specialist_results: Record<string, null | Record<string, unknown>>;
  draft_packet: Packet | null;
  human_edits: Array<Record<string, unknown>>;
  human_decision: null | {
    case_id: string;
    decision_version: number;
    reviewer_id: string;
    action: "approve" | "reject" | "request_info";
    edits?: Array<{ section_key: string; body: string }>;
  };
  write_preview: WritePreview | null;
  write_result: null | {
    idempotency_key: string;
    record_id: string;
    record_version: number;
    committed: boolean;
    duplicate_suppressed: boolean;
    simulated: true;
  };
};

export type QueueItem = {
  case_id: string;
  product: string;
  vendor: string;
  requester: string;
  status: QueueStatus;
  route: RiskRoute;
  match: string;
  match_detail: string;
  stage: string;
  updated: string;
  owner: string;
  state: ReviewState;
};

export type AuditEvent = {
  event_id: string;
  event_type: string;
  case_id: string;
  occurred_at: string;
  actor_type: "requester" | "reviewer" | "system" | "model";
  actor_id?: string;
  workflow_version?: string;
  policy_version?: string;
  decision_version?: number | null;
  detail?: Record<string, unknown>;
};

export type CaseActionResponse = {
  state: ReviewState;
  queue_item: QueueItem;
  audit_events: AuditEvent[];
  simulated: true;
};

export type CaseIntakeInput = {
  product_name: string;
  vendor_name: string;
  requester: { name: string; email: string; department?: string };
  use_case: string;
  expected_users: number;
  platform: string[];
  data_classification: "public" | "internal" | "confidential" | "level1" | "level2" | "unknown";
  estimated_cost_usd: number;
  integrations: string[];
  uses_sso: boolean;
  uses_ai: boolean;
  accessibility_context?: string;
  official_domain?: string;
  classroom_or_public_use: boolean;
};

export type ReviewDecisionInput = {
  decision_version: number;
  reviewer_id: string;
  action: "approve" | "reject" | "request_info";
  decided_at: string;
  comments?: string;
  edits?: Array<{ section_key: string; body: string }>;
};

export type VendorRecord = {
  workspace_id: string;
  vendor_id: string;
  name: string;
  official_domain: string | null;
};
export type VendorProduct = { workspace_id: string; product_id: string; vendor_id: string; name: string };
export type VendorContact = {
  workspace_id: string;
  contact_id: string;
  vendor_id: string;
  name: string;
  email: string;
};
export type InviteStatus = "issued" | "opened" | "in_progress" | "submitted" | "revoked" | "expired";
export type InviteProjection = {
  workspace_id: string;
  invite_id: string;
  case_id: string;
  product_id: string;
  contact_id: string;
  issued_at: string;
  expires_at: string;
  status: InviteStatus;
  opened_at: string | null;
  revoked_at: string | null;
  submitted_at: string | null;
  replaced_invite_id: string | null;
};
export type VendorSubmission = {
  workspace_id: string;
  submission_id: string;
  invite_id: string;
  case_id: string;
  product_id: string;
  version: number;
  status: "draft" | "finalized";
  trust_center_url: string | null;
  answers: Record<string, string>;
  evidence_artifact_ids: string[];
  coverage_ids: string[];
  updated_at: string | null;
  finalized_at: string | null;
};
export type VendorQuestion = { requirement_id: string; question: string; expected_evidence: string[] };
export type VendorInviteView = {
  invite: Pick<InviteProjection, "invite_id" | "case_id" | "expires_at" | "status">;
  vendor: Pick<VendorRecord, "vendor_id" | "name">;
  product: Pick<VendorProduct, "product_id" | "name">;
  contact: Pick<VendorContact, "contact_id" | "name" | "email">;
  submission: VendorSubmission;
  questions: VendorQuestion[];
};
export type EvidenceMetadata = { filename: string; content_type: string; size_bytes: number; sha256: string };
export type EvidenceArtifact = EvidenceMetadata & {
  workspace_id: string;
  artifact_id: string;
  submission_id: string;
  untrusted: true;
};
export type PresignedUpload = { url: string; method?: "PUT" | "POST"; headers?: Record<string, string>; fields?: Record<string, string> };
export type EvidenceRegistration = EvidenceArtifact & { upload?: PresignedUpload | null };
export type EvidenceUploadResult = EvidenceArtifact & { transfer: "uploaded" | "simulated"; notice?: string };
export type ReviewProfileVersion = {
  workspace_id: string;
  profile_version_id: string;
  profile_key: string;
  version: number;
  created_at: string;
  status: "draft" | "activated";
  fixture_tested_at: string | null;
};
export type ReviewRun = {
  workspace_id: string;
  run_id: string;
  case_id: string;
  run_version: number;
  submission_id: string;
  created_at: string;
  unresolved_requirement_ids: string[];
};
export type CatalogSearchResponse = {
  matches: CatalogCandidate[];
  semantic_disclosure: string;
  catalog_membership_is_approval: false;
};

export type CatalogListItem = {
  record_id: string;
  canonical_name: string;
  vendor: string;
  product?: string | null;
  aliases?: string[] | null;
  platform?: string | null;
  audience?: string | null;
  department?: string | null;
  support_flag?: string | null;
  license_flag?: string | null;
  source_row?: number | null;
};
export type CatalogListResponse = {
  items: CatalogListItem[];
  total: number;
  offset: number;
  limit: number;
  catalog_membership_is_approval: false;
};

export type PacketPdfResponse = {
  view_url?: string | null;
  content_type?: string | null;
  size_bytes?: number | null;
  pdf_sha256?: string | null;
  simulated?: boolean;
};
export type ReviewerRecordContext = {
  invites: InviteProjection[];
  contacts: VendorContact[];
  profiles: ReviewProfileVersion[];
  runs: ReviewRun[];
  catalog: CatalogSearchResponse | null;
};

export class ReviewApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly correlationId: string | null;

  constructor(status: number, code: string, message: string, correlationId: string | null = null) {
    super(message);
    this.name = "ReviewApiError";
    this.status = status;
    this.code = code;
    this.correlationId = correlationId;
  }
}

type FetchLike = typeof fetch;
type ClientOptions = { baseUrl?: string; mode?: ApiMode; fetchImpl?: FetchLike; authProvider?: ReviewerAuthProvider };

function configuredMode(): ApiMode {
  return import.meta.env.VITE_REVIEW_DATA_MODE === "fixture" ? "fixture" : "live";
}

function authorization(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}` };
}

export function vendorInviteUrl(origin: string, token: string): string {
  const base = origin.replace(/\/$/, "");
  return `${base}/intake#token=${encodeURIComponent(token)}`;
}

async function sha256(file: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

type SecureRandomSource = {
  randomUUID?: () => string;
  getRandomValues: (array: Uint8Array) => Uint8Array;
};

export function secureCorrelationId(source: SecureRandomSource = globalThis.crypto): string {
  if (typeof source.randomUUID === "function") return source.randomUUID.call(source);
  const bytes = source.getRandomValues.call(source, new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function fixtureId(prefix: string): string {
  return `${prefix}-${secureCorrelationId()}`;
}

function fixtureReviewState(input: CaseIntakeInput, caseId: string): ReviewState {
  return {
    case_id: caseId,
    status: "intake",
    workflow_version: "fixture",
    case_input: { ...input, classroom_or_public_use: input.classroom_or_public_use },
    software_candidates: [],
    confirmed_match_id: null,
    policy_result: null,
    specialist_results: {},
    draft_packet: null,
    human_edits: [],
    human_decision: null,
    write_preview: null,
    write_result: null,
  };
}

function createFixtureAdapter() {
  const workspace_id = "csub-demo";
  const vendors: VendorRecord[] = [{ workspace_id, vendor_id: "vendor-fixture", name: "Fixture Vendor", official_domain: "fixture.example" }];
  const products: VendorProduct[] = [{ workspace_id, product_id: "product-fixture", vendor_id: "vendor-fixture", name: "Fixture Product" }];
  const contacts: VendorContact[] = [{ workspace_id, contact_id: "contact-fixture", vendor_id: "vendor-fixture", name: "Fixture Contact", email: "contact@fixture.example" }];
  const invites: InviteProjection[] = [];
  const profiles: ReviewProfileVersion[] = [{ workspace_id, profile_version_id: "security-v1", profile_key: "security", version: 1, created_at: "2026-07-15T08:00:00Z", status: "activated", fixture_tested_at: "2026-07-15T07:50:00Z" }];
  const runs: ReviewRun[] = [];
  const submission: VendorSubmission = { workspace_id, submission_id: "submission-fixture", invite_id: "invite-fixture", case_id: "FIXTURE-CASE", product_id: "product-fixture", version: 1, status: "draft", trust_center_url: null, answers: {}, evidence_artifact_ids: [], coverage_ids: [], updated_at: null, finalized_at: null };
  const questions: VendorQuestion[] = [
    { requirement_id: "SECURITY.EVIDENCE", question: "What current security evidence supports this product?", expected_evidence: ["security document"] },
    { requirement_id: "ACCESSIBILITY.CONFORMANCE", question: "What accessibility conformance evidence is available?", expected_evidence: ["VPAT or ACR"] },
  ];
  const artifacts: EvidenceArtifact[] = [];
  const covered = new Set<string>();
  return { workspace_id, vendors, products, contacts, invites, profiles, runs, submission, questions, artifacts, covered };
}

export function createReviewApiClient(options: ClientOptions = {}) {
  const baseUrl = (options.baseUrl ?? import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/$/, "");
  const mode = options.mode ?? configuredMode();
  const runFetch = (input: RequestInfo | URL, init?: RequestInit) => (options.fetchImpl ?? globalThis.fetch)(input, init);
  const authProvider = options.authProvider ?? reviewerAuth;
  const fixture = createFixtureAdapter();

  function fixtureInviteView(markOpen = false): VendorInviteView {
    let invite = fixture.invites[0];
    if (!invite) {
      const now = new Date();
      invite = { workspace_id: fixture.workspace_id, invite_id: "invite-fixture", case_id: fixture.submission.case_id, product_id: "product-fixture", contact_id: "contact-fixture", issued_at: now.toISOString(), expires_at: new Date(now.getTime() + 7 * 86400000).toISOString(), status: "issued", opened_at: null, revoked_at: null, submitted_at: null, replaced_invite_id: null };
      fixture.invites.push(invite);
    }
    if (markOpen && invite.status === "issued") {
      invite = { ...invite, status: "opened", opened_at: new Date().toISOString() };
      fixture.invites[0] = invite;
    }
    return {
      invite: { invite_id: invite.invite_id, case_id: invite.case_id, expires_at: invite.expires_at, status: invite.status },
      vendor: { vendor_id: fixture.vendors[0].vendor_id, name: fixture.vendors[0].name },
      product: { product_id: fixture.products[0].product_id, name: fixture.products[0].name },
      contact: { contact_id: fixture.contacts[0].contact_id, name: fixture.contacts[0].name, email: fixture.contacts[0].email },
      submission: { ...fixture.submission, answers: { ...fixture.submission.answers }, evidence_artifact_ids: [...fixture.submission.evidence_artifact_ids], coverage_ids: [...fixture.submission.coverage_ids] },
      questions: suppressResolvedQuestions(fixture.questions, fixture.submission.answers, fixture.covered),
    };
  }

  const inFlight = new Map<string, Promise<unknown>>();

  function singleFlight<T>(key: string, operation: () => Promise<T>): Promise<T> {
    const current = inFlight.get(key) as Promise<T> | undefined;
    if (current) return current;
    const started = operation().finally(() => {
      if (inFlight.get(key) === started) inFlight.delete(key);
    });
    inFlight.set(key, started);
    return started;
  }

  async function request<T>(path: string, init?: RequestInit, audience: "reviewer" | "vendor" = "reviewer"): Promise<T> {
    if (mode === "fixture") {
      throw new ReviewApiError(400, "fixture_network_blocked", "Fixture mode cannot call the live API.");
    }
    const headers = new Headers({
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    });
    if (!headers.has("X-Correlation-Id")) headers.set("X-Correlation-Id", secureCorrelationId());
    if (audience === "reviewer") {
      const accessToken = authProvider.getAccessToken();
      if (!accessToken) {
        throw new ReviewApiError(401, "reviewer_sign_in_required", "Your reviewer session is unavailable or expired. Sign in again.", headers.get("X-Correlation-Id"));
      }
      headers.set("Authorization", `Bearer ${accessToken}`);
    }
    const response = await runFetch(`${baseUrl}${path}`, {
      ...init,
      headers,
    });
    const payload = await response.json().catch(() => null) as null | { error?: { code?: string; message?: string; correlation_id?: string } };
    if (!response.ok) {
      if (audience === "reviewer" && response.status === 401) authProvider.handleUnauthorized();
      const correlationId = payload?.error?.correlation_id || response.headers.get("X-Correlation-Id") || headers.get("X-Correlation-Id");
      throw new ReviewApiError(response.status, payload?.error?.code || "request_failed", payload?.error?.message || `Request failed with status ${response.status}`, correlationId);
    }
    return payload as T;
  }

  const fixtureOnly = <T>(value: T): Promise<T> => Promise.resolve(value);

  return {
    mode,
    async listQueue(): Promise<QueueItem[]> {
      if (mode === "fixture") return [];
      return (await request<{ items: QueueItem[] }>("/review-queue")).items;
    },
    createCase(input: CaseIntakeInput): Promise<{ case_id: string; state: ReviewState }> {
      if (mode === "fixture") {
        const caseId = fixtureId("FIXTURE-CASE");
        return fixtureOnly({ case_id: caseId, state: fixtureReviewState(input, caseId) });
      }
      return request("/cases", { method: "POST", body: JSON.stringify(input) });
    },
    analyzeCase(caseId: string, confirmedMatchId?: string): Promise<CaseActionResponse> {
      return request(`/cases/${encodeURIComponent(caseId)}/analyze`, { method: "POST", body: JSON.stringify(confirmedMatchId ? { confirmed_match_id: confirmedMatchId, reviewer_id: "alex.reviewer@example.edu" } : {}) });
    },
    rerunAnalysis(caseId: string, customInstruction: string): Promise<CaseActionResponse> {
      return request(`/cases/${encodeURIComponent(caseId)}/analyze`, { method: "POST", body: JSON.stringify({ reviewer_id: "alex.reviewer@example.edu", rerun: true, custom_instruction: customInstruction }) });
    },
    recordDecision(caseId: string, decision: ReviewDecisionInput): Promise<CaseActionResponse> {
      return request(`/cases/${encodeURIComponent(caseId)}/review`, { method: "POST", body: JSON.stringify({ case_id: caseId, ...decision }) });
    },
    previewWriteback(caseId: string): Promise<CaseActionResponse> {
      return request(`/cases/${encodeURIComponent(caseId)}/servicenow/preview`, { method: "POST" });
    },
    commitWriteback(caseId: string, expectedVersion: number): Promise<CaseActionResponse> {
      return request(`/cases/${encodeURIComponent(caseId)}/servicenow/commit`, { method: "POST", body: JSON.stringify({ second_confirmation: true, expected_version: expectedVersion }) });
    },
    async listVendors(): Promise<VendorRecord[]> {
      if (mode === "fixture") return fixtureOnly([...fixture.vendors]);
      return (await request<{ items: VendorRecord[] }>("/vendors")).items;
    },
    async createVendor(input: { name: string; official_domain?: string }): Promise<VendorRecord> {
      if (mode === "fixture") {
        const value = { workspace_id: fixture.workspace_id, vendor_id: fixtureId("vendor"), name: input.name, official_domain: input.official_domain ?? null };
        fixture.vendors.push(value);
        return value;
      }
      return request("/vendors", { method: "POST", body: JSON.stringify(input) });
    },
    async listProducts(vendorId?: string): Promise<VendorProduct[]> {
      if (mode === "fixture") return fixture.products.filter((item) => !vendorId || item.vendor_id === vendorId);
      const query = vendorId ? `?vendor_id=${encodeURIComponent(vendorId)}` : "";
      return (await request<{ items: VendorProduct[] }>(`/vendor-products${query}`)).items;
    },
    async createProduct(input: { vendor_id: string; name: string }): Promise<VendorProduct> {
      if (mode === "fixture") {
        const value = { workspace_id: fixture.workspace_id, product_id: fixtureId("product"), ...input };
        fixture.products.push(value);
        return value;
      }
      return request("/vendor-products", { method: "POST", body: JSON.stringify(input) });
    },
    async listContacts(vendorId?: string): Promise<VendorContact[]> {
      if (mode === "fixture") return fixture.contacts.filter((item) => !vendorId || item.vendor_id === vendorId);
      const query = vendorId ? `?vendor_id=${encodeURIComponent(vendorId)}` : "";
      return (await request<{ items: VendorContact[] }>(`/vendor-contacts${query}`)).items;
    },
    async createContact(input: { vendor_id: string; name: string; email: string }): Promise<VendorContact> {
      if (mode === "fixture") {
        const value = { workspace_id: fixture.workspace_id, contact_id: fixtureId("contact"), ...input };
        fixture.contacts.push(value);
        return value;
      }
      return request("/vendor-contacts", { method: "POST", body: JSON.stringify(input) });
    },
    issueInvite(caseId: string, contactId: string): Promise<{ invite: InviteProjection; token: string }> {
      return singleFlight(`issue:${caseId}:${contactId}`, async () => {
        if (mode === "fixture") {
          const now = new Date();
          const invite: InviteProjection = { workspace_id: fixture.workspace_id, invite_id: fixtureId("invite"), case_id: caseId, product_id: fixture.products[0]?.product_id ?? "product-fixture", contact_id: contactId, issued_at: now.toISOString(), expires_at: new Date(now.getTime() + 7 * 86400000).toISOString(), status: "issued", opened_at: null, revoked_at: null, submitted_at: null, replaced_invite_id: null };
          fixture.invites.push(invite);
          return { invite, token: fixtureId("opaque") };
        }
        return request(`/cases/${encodeURIComponent(caseId)}/invites`, { method: "POST", body: JSON.stringify({ contact_id: contactId }) });
      });
    },
    rotateInvite(inviteId: string): Promise<{ invite: InviteProjection; token: string }> {
      return singleFlight(`rotate:${inviteId}`, async () => {
        if (mode === "fixture") {
          const source = fixture.invites.find((item) => item.invite_id === inviteId);
          if (!source) throw new ReviewApiError(404, "invite_not_found", "Invitation was not found.");
          const now = new Date();
          if (source.status !== "submitted" && source.status !== "expired") {
            source.status = "revoked";
            source.revoked_at = now.toISOString();
          }
          const invite: InviteProjection = { ...source, invite_id: fixtureId("invite"), issued_at: now.toISOString(), expires_at: new Date(now.getTime() + 7 * 86400000).toISOString(), status: "issued", opened_at: null, revoked_at: null, submitted_at: null, replaced_invite_id: source.invite_id };
          fixture.invites.push(invite);
          return { invite, token: fixtureId("opaque") };
        }
        return request(`/invites/${encodeURIComponent(inviteId)}/resend`, { method: "POST", body: "{}" });
      });
    },
    async revokeInvite(inviteId: string): Promise<InviteProjection> {
      if (mode === "fixture") {
        const invite = fixture.invites.find((item) => item.invite_id === inviteId);
        if (!invite) throw new ReviewApiError(404, "invite_not_found", "Invitation was not found.");
        if (invite.status !== "submitted" && invite.status !== "expired") {
          invite.status = "revoked";
          invite.revoked_at = new Date().toISOString();
        }
        return { ...invite };
      }
      return request(`/invites/${encodeURIComponent(inviteId)}/revoke`, { method: "POST", body: "{}" });
    },
    async listInvites(caseId: string): Promise<InviteProjection[]> {
      if (mode === "fixture") return fixture.invites.filter((item) => item.case_id === caseId);
      return (await request<{ items: InviteProjection[] }>(`/cases/${encodeURIComponent(caseId)}/invites`)).items;
    },
    async listProfiles(): Promise<ReviewProfileVersion[]> {
      if (mode === "fixture") return [...fixture.profiles];
      return (await request<{ items: ReviewProfileVersion[] }>("/review-profiles")).items;
    },
    async listReviewRuns(caseId: string): Promise<ReviewRun[]> {
      if (mode === "fixture") return fixture.runs.filter((item) => item.case_id === caseId);
      return (await request<{ items: ReviewRun[] }>(`/cases/${encodeURIComponent(caseId)}/review-runs`)).items;
    },
    async searchCatalog(query: string, vendor?: string): Promise<CatalogSearchResponse> {
      if (mode === "fixture") return { matches: [{ record_id: "fixture-row-1", canonical_name: query, vendor: vendor ?? "Fixture Vendor", source_row: 1, match_method: "fuzzy", score: 0.86, requires_human_confirmation: true }], semantic_disclosure: "Fixture candidate", catalog_membership_is_approval: false };
      const params = new URLSearchParams({ q: query });
      if (vendor) params.set("vendor", vendor);
      return request(`/catalog/search?${params.toString()}`);
    },
    confirmCatalogMatch(recordId: string, matchMethod: MatchMethod, reviewerId: string): Promise<{ confirmed: true; approval_granted: false }> {
      if (mode === "fixture") return fixtureOnly({ confirmed: true, approval_granted: false });
      return request(`/catalog/matches/${encodeURIComponent(recordId)}/confirm`, { method: "POST", body: JSON.stringify({ match_method: matchMethod, reviewer_id: reviewerId }) });
    },
    async listCatalog(query = "", limit = 20, offset = 0): Promise<CatalogListResponse> {
      if (mode === "fixture") {
        const rows: CatalogListItem[] = [
          { record_id: "row-238", canonical_name: "Canvas", vendor: "Instructure", product: "Canvas LMS", platform: "Web", audience: "Faculty and students", department: "Academic Technology", support_flag: "Supported", license_flag: "Institution license", source_row: 238 },
          { record_id: "row-144", canonical_name: "Qualtrics XM", vendor: "Qualtrics", product: "Experience Management", platform: "Web", audience: "Staff", department: "Institutional Research", support_flag: "Supported", license_flag: "Site license", source_row: 144 },
          { record_id: "row-091", canonical_name: "Zoom", vendor: "Zoom Video Communications", product: "Meetings", platform: "Web, Desktop", audience: "All", department: "IT", support_flag: "Supported", license_flag: "Enterprise", source_row: 91 },
          { record_id: "row-172", canonical_name: "LabArchives", vendor: "LabArchives, LLC", product: "Electronic Lab Notebook", platform: "Web", audience: "Research", department: "College of Science", support_flag: "Conditional", license_flag: "Departmental", source_row: 172 },
        ];
        const q = query.trim().toLowerCase();
        const filtered = q ? rows.filter((row) => `${row.canonical_name} ${row.vendor} ${row.product ?? ""}`.toLowerCase().includes(q)) : rows;
        return fixtureOnly({ items: filtered.slice(offset, offset + limit), total: filtered.length, offset, limit, catalog_membership_is_approval: false });
      }
      const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
      if (query.trim()) params.set("q", query.trim());
      const payload = await request<Partial<CatalogListResponse> & { records?: CatalogListItem[] }>(`/catalog?${params.toString()}`);
      const items = payload.items ?? payload.records ?? [];
      return {
        items,
        total: typeof payload.total === "number" ? payload.total : items.length,
        offset: typeof payload.offset === "number" ? payload.offset : offset,
        limit: typeof payload.limit === "number" ? payload.limit : limit,
        catalog_membership_is_approval: false,
      };
    },
    getPacketPdf(caseId: string): Promise<PacketPdfResponse> {
      if (mode === "fixture") return fixtureOnly({ view_url: null, content_type: "application/pdf", size_bytes: 0, pdf_sha256: "simulated-fixture", simulated: true });
      return request(`/cases/${encodeURIComponent(caseId)}/packet/pdf`);
    },
    resolveInvite(token: string): Promise<VendorInviteView> {
      if (mode === "fixture") return fixtureOnly(fixtureInviteView());
      return request("/vendor/invites/current", { headers: authorization(token) }, "vendor");
    },
    openInvite(token: string): Promise<VendorInviteView> {
      if (mode === "fixture") return fixtureOnly(fixtureInviteView(true));
      return request("/vendor/invites/current/open", { method: "POST", headers: authorization(token) }, "vendor");
    },
    async getVendorQuestions(token: string): Promise<VendorQuestion[]> {
      if (mode === "fixture") return fixtureInviteView().questions;
      return (await request<{ items: VendorQuestion[] }>("/vendor/invites/current/questions", { headers: authorization(token) }, "vendor")).items;
    },
    registerEvidence(token: string, metadata: EvidenceMetadata): Promise<EvidenceRegistration> {
      if (mode === "fixture") {
        const artifact: EvidenceArtifact = { ...metadata, workspace_id: fixture.workspace_id, artifact_id: fixtureId("evidence"), submission_id: fixture.submission.submission_id, untrusted: true };
        fixture.artifacts.push(artifact);
        fixture.submission.evidence_artifact_ids.push(artifact.artifact_id);
        fixture.submission.updated_at = new Date().toISOString();
        return fixtureOnly(artifact);
      }
      return request("/vendor/invites/current/evidence", { method: "POST", headers: authorization(token), body: JSON.stringify(metadata) }, "vendor");
    },
    async uploadEvidence(token: string, file: File): Promise<EvidenceUploadResult> {
      const registration = await this.registerEvidence(token, { filename: file.name, content_type: file.type || "application/octet-stream", size_bytes: file.size, sha256: await sha256(file) });
      if (!registration.upload?.url) {
        return { ...registration, transfer: "simulated", notice: "Evidence metadata was saved, but this API did not provide a presigned upload. The file bytes stayed in this browser." };
      }
      const uploadUrl = new URL(registration.upload.url, globalThis.location?.origin);
      if (uploadUrl.protocol !== "https:" && uploadUrl.hostname !== "127.0.0.1" && uploadUrl.hostname !== "localhost") {
        throw new ReviewApiError(400, "invalid_upload_url", "The evidence API returned an unsafe upload URL.");
      }
      const method = registration.upload.method ?? "PUT";
      let body: BodyInit = file;
      if (method === "POST") {
        const form = new FormData();
        Object.entries(registration.upload.fields ?? {}).forEach(([key, value]) => form.append(key, value));
        form.append("file", file);
        body = form;
      }
      const uploadHeaders = new Headers(registration.upload.headers);
      uploadHeaders.delete("Authorization");
      const uploadResponse = await runFetch(uploadUrl, { method, headers: uploadHeaders, body });
      if (!uploadResponse.ok) throw new ReviewApiError(uploadResponse.status, "upload_failed", "The presigned evidence upload failed.");
      return { ...registration, transfer: "uploaded" };
    },
    saveTrustCenter(token: string, trustCenterUrl: string): Promise<VendorSubmission> {
      if (mode === "fixture") {
        fixture.submission.trust_center_url = trustCenterUrl;
        fixture.submission.updated_at = new Date().toISOString();
        return fixtureOnly({ ...fixture.submission });
      }
      return request("/vendor/invites/current/trust-center", { method: "POST", headers: authorization(token), body: JSON.stringify({ trust_center_url: trustCenterUrl }) }, "vendor");
    },
    saveAnswers(token: string, answers: Record<string, string>): Promise<VendorSubmission> {
      if (mode === "fixture") {
        Object.assign(fixture.submission.answers, answers);
        fixture.submission.updated_at = new Date().toISOString();
        return fixtureOnly({ ...fixture.submission, answers: { ...fixture.submission.answers } });
      }
      return request("/vendor/invites/current/answers", { method: "POST", headers: authorization(token), body: JSON.stringify({ answers }) }, "vendor");
    },
    addCoverage(token: string, requirementId: string, evidenceArtifactIds: string[]): Promise<{ coverage_id: string }> {
      if (mode === "fixture") {
        const coverageId = fixtureId("coverage");
        fixture.covered.add(requirementId);
        fixture.submission.coverage_ids.push(coverageId);
        fixture.submission.updated_at = new Date().toISOString();
        return fixtureOnly({ coverage_id: coverageId });
      }
      return request("/vendor/invites/current/coverage", { method: "POST", headers: authorization(token), body: JSON.stringify({ requirement_id: requirementId, evidence_artifact_ids: evidenceArtifactIds }) }, "vendor");
    },
    finalizeVendorSubmission(token: string): Promise<VendorSubmission> {
      if (mode === "fixture") {
        const now = new Date().toISOString();
        fixture.submission.status = "finalized";
        fixture.submission.finalized_at = now;
        fixture.submission.updated_at = now;
        if (fixture.invites[0]) fixture.invites[0] = { ...fixture.invites[0], status: "submitted", submitted_at: now };
        return fixtureOnly({ ...fixture.submission });
      }
      return request("/vendor/invites/current/finalize", { method: "POST", headers: authorization(token) }, "vendor");
    },
    async loadReviewerRecord(caseId: string, productName: string, vendorName: string): Promise<ReviewerRecordContext> {
      const [vendors, invites, profiles, runs, catalog] = await Promise.all([
        this.listVendors(),
        this.listInvites(caseId),
        this.listProfiles(),
        this.listReviewRuns(caseId),
        this.searchCatalog(productName, vendorName),
      ]);
      const vendor = vendors.find((item) => item.name.toLowerCase() === vendorName.toLowerCase());
      const contacts = vendor ? await this.listContacts(vendor.vendor_id) : [];
      return { invites, contacts, profiles, runs, catalog };
    },
  };
}

export const reviewApi = createReviewApiClient();

export function requiresReviewerConfirmation(candidate: Pick<SoftwareCandidate, "match_method" | "requires_confirmation"> | Pick<CatalogCandidate, "match_method" | "requires_human_confirmation">): boolean {
  return candidate.match_method === "fuzzy" || candidate.match_method === "semantic" || ("requires_confirmation" in candidate ? candidate.requires_confirmation : candidate.requires_human_confirmation);
}

export function suppressResolvedQuestions(questions: VendorQuestion[], answers: Record<string, string>, coveredRequirementIds: ReadonlySet<string>): VendorQuestion[] {
  return questions.filter((question) => !answers[question.requirement_id]?.trim() && !coveredRequirementIds.has(question.requirement_id));
}

export function queueItemToSummary(item: QueueItem): ReviewSummary {
  return { id: item.case_id, product: item.product, vendor: item.vendor, requester: item.requester, status: item.status, route: item.route, match: item.match, matchDetail: item.match_detail, stage: item.stage, updated: item.updated, owner: item.owner };
}

export function packetEditSection(packet: Packet | null): PacketSection | null {
  if (!packet) return null;
  const preferredKey = packet.packet_type === "low_risk" ? "recommendation" : "committee_routing";
  return packet.sections.find((section) => section.key === preferredKey && section.editable) ?? packet.sections.find((section) => section.editable) ?? null;
}

export function packetToDraft(packet: Packet | null): string {
  return packetEditSection(packet)?.body ?? "";
}

export function decisionVersion(state: ReviewState, hasPacketEdits = false): number {
  const packetVersion = state.draft_packet?.packet_version || 1;
  return state.human_decision || hasPacketEdits ? packetVersion + 1 : packetVersion;
}

export function consumeInviteTokenFromFragment(
  location: Pick<Location, "hash" | "pathname" | "search">,
  history: Pick<History, "replaceState">,
  storage?: Pick<Storage, "getItem" | "setItem">,
): string | null {
  const fragment = location.hash.replace(/^#/, "");
  const storageKey = "vetted.vendor.invite.token";
  if (!fragment) return storage?.getItem(storageKey)?.trim() || null;
  const parameters = new URLSearchParams(fragment.includes("=") ? fragment : `token=${fragment}`);
  const token = parameters.get("token")?.trim() || parameters.get("invite")?.trim() || null;
  if (token) storage?.setItem(storageKey, token);
  history.replaceState(null, "", `${location.pathname}${location.search}`);
  return token;
}
