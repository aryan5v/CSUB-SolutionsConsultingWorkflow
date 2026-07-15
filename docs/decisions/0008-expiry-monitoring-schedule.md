# ADR 0008: Durable schedule for post-approval expiry monitoring

- Status: Accepted
- Date: 2026-07-15

## Context

Issue #53 requires approved products to be monitored for expiring evidence and
a scoped re-review opened before coverage lapses, using "a durable AWS schedule
to notify the owner and vendor at configurable lead times". The deterministic
review Lambda already exposes the sweep as `POST /renewals/run` (reviewer-
triggered) and the projection as `GET /renewals`, but review of PR #55 found
that neither route was registered in the API Gateway stack and no schedule
existed, so the feature never ran automatically.

## Decision

`PlatformStack` registers `GET /renewals` and `POST /renewals/run` as
Cognito-JWT-protected reviewer routes (same pattern as the other reviewer
routes) and adds one `AWS::Scheduler::Schedule` (EventBridge Scheduler) that
invokes the existing case-proxy Lambda directly on a fixed daily cadence.

- The schedule sends the payload `{"scheduled_task": "renewals_run"}`. The
  Lambda handler detects this synthetic event and runs `run_expiry_sweep()`,
  persisting the mutated snapshot. Invoking the Lambda directly (rather than
  calling API Gateway) means the Scheduler's IAM role is the authorization and
  no reviewer JWT is minted for automation.
- A dedicated Scheduler execution role may invoke only the case-proxy function
  (`lambda:InvokeFunction` scoped to that ARN), with an `aws:SourceAccount`
  confused-deputy guard on its trust policy.
- Cadence is `rate(1 day)` in `America/Los_Angeles`. Lead-time thresholds
  (default 60/30/7 days) remain configurable in the deterministic backend; the
  schedule only decides *how often the backend re-evaluates*, never policy.

### Purpose / region / cost / teardown (AGENTS.md)

- **Purpose:** run the evidence-expiry sweep automatically so lapses are caught
  without a human trigger.
- **Region:** the stack region (us-west-2 per project guardrails).
- **Ownership:** integration/AWS workstream, same as the rest of `PlatformStack`.
- **Cost:** one schedule (Scheduler free tier covers far more than one daily
  invocation) plus one short Lambda run per day — negligible.
- **Data classification:** none new; the sweep reads/writes existing workspace
  projections. Notice emails carry only hashed recipients in event records.
- **Teardown:** destroyed with the stack (`removalPolicy` DESTROY in demo
  environments); the schedule holds no external state.

## Consequences

- The renewals feature is reachable (routes) and runs automatically (schedule)
  once the review-agent Lambda is deployed.
- The sweep stays idempotent and claim-guarded, so a scheduled run, a manual
  reviewer run, and a retried invocation cannot duplicate notices or cases.
- Human ownership is preserved: the sweep never mails a new submission link or
  revokes an approval; refreshed-evidence invites remain reviewer-issued.
