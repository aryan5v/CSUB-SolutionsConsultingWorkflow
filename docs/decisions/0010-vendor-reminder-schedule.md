# ADR 0010: Weekly vendor reminder schedule

- Status: Accepted
- Date: 2026-07-15
- Owner: CSUB VETTED integration owner
- Region: `us-west-2` (the approved VETTED sandbox stack region)
- Related: [PRD](../PRD.md) (FR-1, sec 6, sec 7), [PLAN](../../PLAN.md) (Wednesday vendor workflow), GitHub issue #37

## Context

Incomplete vendor evidence requests need a predictable reminder without relying
on a reviewer to keep a browser session open. Concurrent Lambda cold starts or
Scheduler retries must not send duplicate mail, and a transport failure must not
silently satisfy the weekly cadence. Reminder records contain workflow
identifiers and hashed recipient metadata; the contact address is used only at
the email adapter boundary and is not copied into the delivery outbox or
integration-event detail.

## Decision

`PlatformStack` creates one EventBridge Scheduler schedule in `us-west-2`. It
runs every Monday at 09:00 in `America/Los_Angeles` and invokes the existing case
Lambda with the fixed payload `{"scheduled_task":"reminders_run"}`. The Lambda
recognizes only that scheduled task, restores the fixed `csub-demo` workspace,
runs the same reminder sweep as the JWT-protected `POST /reminders/run` reviewer
route, and persists only a sweep that recorded an attempt.

The Scheduler assumes a dedicated role whose trust policy is restricted to
`scheduler.amazonaws.com`, the deployment account (`aws:SourceAccount`), and the
exact schedule ARN. Its only permission is `lambda:InvokeFunction` on the case
Lambda. Scheduler retries are bounded to two attempts within one hour; the
application additionally claims each `workspace + dedupe key` in the existing
DynamoDB `IdempotencyTable` before email. Claim and settlement are conditional
atomic updates, and failed delivery retries are capped per cadence period.

The schedule processes the prototype's sanitized vendor-contact workflow data.
Data classification is **internal operational metadata**: case/invite IDs,
delivery state, attempt count, and a SHA-256 recipient digest. The outbox and
audit event never store a raw recipient address or message body. Email content
uses the existing case-scoped invitation link and deterministic missing-item
copy.

Expected incremental cost is negligible for the prototype: one Scheduler
invocation per week, one short Lambda invocation, and a small number of
on-demand DynamoDB operations, all covered by the existing sandbox budget and
alarms. The integration owner owns monitoring and teardown.

## Consequences and teardown

- Reviewers retain pause/resume controls and delivery history; the public vendor
  status and scoped invitation behavior are unchanged.
- Destroying `PlatformStack` removes the schedule and its dedicated IAM role.
  With `destroyOnRemoval` enabled, the sandbox idempotency table is also removed;
  retained environments follow the existing stack/data retention policy. To
  stop reminders without destroying the stack, disable or delete
  `csub-vendor-reminders-<environment>` before disabling email delivery.
- Rollback is the normal guarded PlatformStack rollback; no data migration or
  new table is required.

Issue #37 remains intentionally limited. VETTED does **not** fabricate or infer
bounce handling, suppression-list state, vendor opt-out/consent policy, or a
monitored question/reply channel. Reminder copy may invite a reply, but no reply
workflow is claimed by the prototype. Those capabilities require confirmed
campus ownership, policy, and an inbound-email design before implementation.
