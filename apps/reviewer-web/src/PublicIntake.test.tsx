import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ReviewStatusCard } from "./PublicIntake";
import type { VendorReviewStatus } from "./api";

const status: VendorReviewStatus = {
  invite: {
    invite_id: "invite-1",
    case_id: "CASE-1",
    expires_at: "2026-07-20T00:00:00Z",
    status: "submitted",
  },
  vendor: { vendor_id: "vendor-1", name: "Example Vendor" },
  product: { product_id: "product-1", name: "Example Product" },
  submission_status: "finalized",
  intake_analysis_complete: true,
  review_stage: "changes_requested",
  outcome: null,
  vendor_visible_comment: "Please update the accessibility evidence.",
  next_actions: ["Upload the current product-specific ACR."],
  checklist: [],
};

describe("PublicIntake review status", () => {
  it("renders only explicit vendor-visible messaging and next actions", () => {
    const unsafeInput = {
      ...status,
      comments: "Internal reviewer finding that must never render.",
    } as VendorReviewStatus & { comments: string };

    const html = renderToStaticMarkup(<ReviewStatusCard status={unsafeInput} />);

    expect(html).toContain("Changes requested");
    expect(html).toContain("Message from your campus reviewer");
    expect(html).toContain("Please update the accessibility evidence.");
    expect(html).toContain("What to do next");
    expect(html).toContain("Upload the current product-specific ACR.");
    expect(html).not.toContain("Internal reviewer finding");
  });
});
