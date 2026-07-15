#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_ENV="${APP_ENV:-development}"
AWS_REGION="${AWS_REGION:-us-west-2}"
FOUNDATION_STACK="${FOUNDATION_STACK:-ReviewFoundationStack}"
PLATFORM_STACK="${PLATFORM_STACK:-PlatformStack}"
RELEASE_SHA=""
ASSEMBLY=""
PLAN=""
OPERATION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --release-sha) RELEASE_SHA="${2:-}"; shift 2 ;;
    --assembly) ASSEMBLY="${2:-}"; shift 2 ;;
    --plan) PLAN="${2:-}"; shift 2 ;;
    --operation) OPERATION="${2:-}"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 64 ;;
  esac
done

if [[ ! "$RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]] || [[ ! -f "$ASSEMBLY/manifest.json" ]]; then
  echo "A full --release-sha and a synthesized --assembly are required" >&2
  exit 64
fi
if [[ "$OPERATION" != "preflight" && "$OPERATION" != "execute" && "$OPERATION" != "recovery" && "$OPERATION" != "cleanup" ]]; then
  echo "--operation must be preflight, execute, recovery, or cleanup" >&2
  exit 64
fi
if [[ "$OPERATION" != "recovery" && -z "$PLAN" ]]; then
  echo "--plan is required for preflight and execute" >&2
  exit 64
fi

mkdir -p "$ROOT/artifacts/deploy"
CDK=(npm --prefix "$ROOT/infra" exec --offline cdk -- --app "$ASSEMBLY")
CONTEXT=(-c "appEnv=$APP_ENV" -c enableAgentCoreServices=false -c enableVectorStores=false -c enableGuardrail=false)

cleanup_prepared() {
  [[ -f "$PLAN" ]] || return 0
  while IFS=$'\t' read -r stack change_set kind; do
    if [[ "$kind" == "changes" ]]; then
      aws cloudformation delete-change-set --stack-name "$stack" \
        --change-set-name "$change_set" --region "$AWS_REGION" >/dev/null 2>&1 || true
    fi
  done <"$PLAN"
}

preflight() {
  : >"$PLAN"
  local run_suffix="${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
  trap cleanup_prepared ERR INT TERM

  # Prepare and inspect every stack before any ExecuteChangeSet call. This
  # prevents a safe Foundation update from partially landing when Platform is
  # later rejected.
  for stack in "$FOUNDATION_STACK" "$PLATFORM_STACK"; do
    local normalized change_set details log status cdk_status
    normalized="$(tr '[:upper:]' '[:lower:]' <<<"$stack" | tr -cd 'a-z0-9-')"
    change_set="vetted-${RELEASE_SHA:0:10}-${run_suffix}-${normalized:0:30}"
    details="$ROOT/artifacts/deploy/${stack}-${RELEASE_SHA:0:12}.json"
    log="$ROOT/artifacts/deploy/${stack}-${RELEASE_SHA:0:12}.log"

    if "${CDK[@]}" deploy "$stack" --exclusively --method prepare-change-set \
      --change-set-name "$change_set" --require-approval never --rollback \
      "${CONTEXT[@]}" 2>&1 | tee "$log"; then
      cdk_status=0
    else
      # Capture the CDK side of the pipeline without letting `set -e` skip the
      # inspectable "no changes" path below. Never convert a real CDK failure
      # into success merely because tee completed.
      cdk_status="${PIPESTATUS[0]}"
    fi

    if ! aws cloudformation describe-change-set --stack-name "$stack" \
      --change-set-name "$change_set" --region "$AWS_REGION" >"$details" 2>/dev/null; then
      if grep -Eiq 'no changes|didn.t contain changes' "$log"; then
        printf '%s\t%s\t%s\n' "$stack" "$change_set" "nochanges" >>"$PLAN"
        continue
      fi
      echo "CloudFormation did not return an inspectable change set for $stack (CDK exit $cdk_status)" >&2
      if [[ $cdk_status -ne 0 ]]; then
        return "$cdk_status"
      fi
      return 2
    fi

    if [[ $cdk_status -ne 0 ]]; then
      echo "CDK failed while preparing the inspectable change set for $stack (exit $cdk_status)" >&2
      aws cloudformation delete-change-set --stack-name "$stack" \
        --change-set-name "$change_set" --region "$AWS_REGION" >/dev/null 2>&1 || true
      return "$cdk_status"
    fi

    if python3 "$ROOT/scripts/deploy/guard_change_set.py" "$details"; then
      status=0
    else
      status=$?
    fi
    if [[ $status -eq 10 ]]; then
      aws cloudformation delete-change-set --stack-name "$stack" \
        --change-set-name "$change_set" --region "$AWS_REGION" >/dev/null 2>&1 || true
      printf '%s\t%s\t%s\n' "$stack" "$change_set" "nochanges" >>"$PLAN"
      continue
    fi
    if [[ $status -ne 0 ]]; then
      aws cloudformation delete-change-set --stack-name "$stack" \
        --change-set-name "$change_set" --region "$AWS_REGION" >/dev/null 2>&1 || true
      return "$status"
    fi
    printf '%s\t%s\t%s\n' "$stack" "$change_set" "changes" >>"$PLAN"
  done

  trap - ERR INT TERM
  echo "All stack change sets passed the fail-closed guard."
}

execute_plan() {
  [[ -s "$PLAN" ]] || { echo "A completed preflight plan is required" >&2; exit 2; }
  while IFS=$'\t' read -r stack change_set kind; do
    [[ "$kind" == "changes" ]] || continue
    "${CDK[@]}" deploy "$stack" --exclusively --method execute-change-set \
      --change-set-name "$change_set" --require-approval never --rollback \
      "${CONTEXT[@]}"
  done <"$PLAN"
}

recover() {
  # Platform consumes Foundation outputs, so restore dependants before their
  # providers. CloudFormation's native rollback remains enabled on each stack.
  for stack in "$PLATFORM_STACK" "$FOUNDATION_STACK"; do
    "${CDK[@]}" deploy "$stack" --exclusively --require-approval never --rollback \
      "${CONTEXT[@]}"
  done
}

case "$OPERATION" in
  preflight) preflight ;;
  execute) execute_plan ;;
  recovery) recover ;;
  cleanup) cleanup_prepared ;;
esac
