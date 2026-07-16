import type { InviteProjection } from "./api";

const ROTATABLE_STATUSES = new Set<InviteProjection["status"]>([
  "issued",
  "opened",
  "in_progress",
]);

export function applyRotatedInvite(
  current: InviteProjection[],
  replacedInviteId: string,
  rotated: InviteProjection,
): InviteProjection[] {
  return [
    rotated,
    ...current
      .filter((invite) => invite.invite_id !== rotated.invite_id)
      .map((invite) =>
        invite.invite_id === replacedInviteId && ROTATABLE_STATUSES.has(invite.status)
          ? {
              ...invite,
              status: "revoked" as const,
              revoked_at: invite.revoked_at ?? rotated.issued_at,
            }
          : invite,
      ),
  ];
}
