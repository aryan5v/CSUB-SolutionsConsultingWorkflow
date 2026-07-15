export type QueueStatus = "Ready for review" | "Analyzing" | "Needs evidence" | "Completed";
export type RiskRoute = "Low risk" | "Medium risk" | "Safe escalation" | "Pending route";

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
  match_method: "exact" | "alias" | "vendor_product" | "fuzzy" | "semantic";
  score: number;
  requires_confirmation: boolean;
  source_row_ref: SourceCoordinates;
};

export type PacketSection = {
  key: string;
  title: string;
  body: string;
  editable: boolean;
};

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

export type CaseActionResponse = {
  state: ReviewState;
  queue_item: QueueItem;
  audit_events: Array<Record<string, unknown>>;
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

export class ReviewApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ReviewApiError";
    this.status = status;
    this.code = code;
  }
}

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  const payload = await response.json().catch(() => null) as null | {
    error?: { code?: string; message?: string };
  };
  if (!response.ok) {
    throw new ReviewApiError(
      response.status,
      payload?.error?.code || "request_failed",
      payload?.error?.message || `Request failed with status ${response.status}`,
    );
  }
  return payload as T;
}

export const reviewApi = {
  async listQueue(): Promise<QueueItem[]> {
    const response = await request<{ items: QueueItem[] }>("/review-queue");
    return response.items;
  },

  createCase(input: CaseIntakeInput): Promise<{ case_id: string; state: ReviewState }> {
    return request("/cases", { method: "POST", body: JSON.stringify(input) });
  },

  analyzeCase(caseId: string, confirmedMatchId?: string): Promise<CaseActionResponse> {
    return request(`/cases/${encodeURIComponent(caseId)}/analyze`, {
      method: "POST",
      body: JSON.stringify(
        confirmedMatchId
          ? { confirmed_match_id: confirmedMatchId, reviewer_id: "alex.reviewer@example.edu" }
          : {},
      ),
    });
  },

  recordDecision(caseId: string, decision: ReviewDecisionInput): Promise<CaseActionResponse> {
    return request(`/cases/${encodeURIComponent(caseId)}/review`, {
      method: "POST",
      body: JSON.stringify({ case_id: caseId, ...decision }),
    });
  },

  previewWriteback(caseId: string): Promise<CaseActionResponse> {
    return request(`/cases/${encodeURIComponent(caseId)}/servicenow/preview`, { method: "POST" });
  },

  commitWriteback(
    caseId: string,
    expectedVersion: number,
  ): Promise<CaseActionResponse> {
    return request(`/cases/${encodeURIComponent(caseId)}/servicenow/commit`, {
      method: "POST",
      body: JSON.stringify({ second_confirmation: true, expected_version: expectedVersion }),
    });
  },
};

export function queueItemToSummary(item: QueueItem): ReviewSummary {
  return {
    id: item.case_id,
    product: item.product,
    vendor: item.vendor,
    requester: item.requester,
    status: item.status,
    route: item.route,
    match: item.match,
    matchDetail: item.match_detail,
    stage: item.stage,
    updated: item.updated,
    owner: item.owner,
  };
}

export function packetEditSection(packet: Packet | null): PacketSection | null {
  if (!packet) return null;
  const preferredKey = packet.packet_type === "low_risk" ? "recommendation" : "committee_routing";
  return packet.sections.find((section) => section.key === preferredKey && section.editable)
    ?? packet.sections.find((section) => section.editable)
    ?? null;
}

export function packetToDraft(packet: Packet | null): string {
  return packetEditSection(packet)?.body ?? "";
}

export function decisionVersion(state: ReviewState, hasPacketEdits = false): number {
  const packetVersion = state.draft_packet?.packet_version || 1;
  return state.human_decision || hasPacketEdits ? packetVersion + 1 : packetVersion;
}
