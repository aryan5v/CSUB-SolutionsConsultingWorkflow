import { describe, expect, it } from "vitest";
import { reviewStageLabel } from "./api";

describe("PublicIntake changes-requested flow", () => {
  it("labels the vendor-safe changes_requested review stage", () => {
    expect(
      reviewStageLabel({ review_stage: "changes_requested", outcome: null }),
    ).toBe("Changes requested");
  });
});
