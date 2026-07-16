import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { EvidenceProcessingList, evidenceNeedsPolling, evidenceStateLabel } from "./EvidenceProcessing";
import type { EvidenceArtifact } from "./api";

function artifact(state: EvidenceArtifact["processing_state"], overrides: Partial<EvidenceArtifact> = {}): EvidenceArtifact {
  return {
    artifact_id: `artifact-${state}`,
    filename: `${state}.pdf`,
    content_type: "application/pdf",
    size_bytes: 1024,
    sha256: "a".repeat(64),
    untrusted: true,
    processing_state: state,
    model_use_allowed: false,
    ...overrides,
  };
}

describe("evidence processing state UI", () => {
  it("renders all reviewable states, warnings, and failure codes", () => {
    const items = [
      artifact("queued"), artifact("processing"), artifact("ready"),
      artifact("failed", { failure_code: "mime_mismatch" }),
      artifact("manual_review", { warnings: ["encrypted PDF requires manual review"] }),
    ];
    const markup = renderToStaticMarkup(<EvidenceProcessingList items={items} emptyMessage="Empty" />);

    for (const label of ["Queued", "Processing", "Ready", "Failed", "Manual review"]) expect(markup).toContain(label);
    expect(markup).toContain("mime mismatch");
    expect(markup).toContain("encrypted PDF requires manual review");
    expect(markup).not.toContain("claim_token");
  });

  it("polls only while queued or processing work remains", () => {
    expect(evidenceNeedsPolling([artifact("queued")])).toBe(true);
    expect(evidenceNeedsPolling([artifact("processing")])).toBe(true);
    expect(evidenceNeedsPolling([artifact("ready"), artifact("manual_review")])).toBe(false);
    expect(evidenceStateLabel(undefined)).toBe("Registered");
  });
});
