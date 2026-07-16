import { describe, expect, it } from "vitest";
import type { InviteProjection } from "./api";
import { applyRotatedInvite } from "./inviteState";

function invite(
  inviteId: string,
  status: InviteProjection["status"],
  overrides: Partial<InviteProjection> = {},
): InviteProjection {
  return {
    workspace_id: "csub-demo",
    invite_id: inviteId,
    case_id: "TR-260714-014",
    product_id: "product-1",
    contact_id: "contact-1",
    issued_at: "2026-07-15T20:00:00Z",
    expires_at: "2026-07-22T20:00:00Z",
    status,
    opened_at: null,
    revoked_at: null,
    submitted_at: null,
    replaced_invite_id: null,
    ...overrides,
  };
}

describe("applyRotatedInvite", () => {
  it("prepends the one-time rotation response and revokes the replaced local invite", () => {
    const original = invite("invite-old", "opened", {
      opened_at: "2026-07-15T20:05:00Z",
    });
    const terminal = invite("invite-submitted", "submitted", {
      submitted_at: "2026-07-15T20:10:00Z",
    });
    const rotated = invite("invite-new", "issued", {
      issued_at: "2026-07-15T20:15:00Z",
      replaced_invite_id: original.invite_id,
    });
    const current = [original, terminal];

    const result = applyRotatedInvite(current, original.invite_id, rotated);

    expect(result).toEqual([
      rotated,
      { ...original, status: "revoked", revoked_at: rotated.issued_at },
      terminal,
    ]);
    expect(current).toEqual([original, terminal]);
  });

  it("is idempotent and preserves terminal invite states", () => {
    const submitted = invite("invite-old", "submitted", {
      submitted_at: "2026-07-15T20:10:00Z",
    });
    const rotated = invite("invite-new", "issued", {
      replaced_invite_id: submitted.invite_id,
    });

    const once = applyRotatedInvite([submitted], submitted.invite_id, rotated);
    const twice = applyRotatedInvite(once, submitted.invite_id, rotated);

    expect(twice).toEqual([rotated, submitted]);
  });
});
