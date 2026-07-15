import type { EvidenceArtifact, EvidenceProcessingState } from "./api";

export function evidenceStateLabel(state: EvidenceProcessingState | undefined): string {
  switch (state) {
    case "queued": return "Queued";
    case "processing": return "Processing";
    case "ready": return "Ready";
    case "failed": return "Failed";
    case "manual_review": return "Manual review";
    default: return "Registered";
  }
}

export function evidenceNeedsPolling(items: EvidenceArtifact[]): boolean {
  return items.some((item) => item.processing_state === "queued" || item.processing_state === "processing");
}

export function EvidenceProcessingList({ items, emptyMessage }: { items: EvidenceArtifact[]; emptyMessage: string }) {
  if (items.length === 0) return <p className="vp-field-hint" role="status">{emptyMessage}</p>;
  return <ul className="vp-file-list" aria-label="Evidence processing states">
    {items.map((item) => <li key={item.artifact_id}>
      <span>
        <strong>{item.filename}</strong>
        <small>{item.detected_content_type ?? item.content_type} · {Math.ceil(item.size_bytes / 1024)} KB</small>
        {item.failure_code && <small className="vp-file-error-message">{item.failure_code.replace(/_/g, " ")}</small>}
        {item.warnings?.map((warning) => <small key={warning}>{warning}</small>)}
      </span>
      <b className={`vp-file-${item.processing_state ?? "ready"}`}>{evidenceStateLabel(item.processing_state)}</b>
    </li>)}
  </ul>;
}
