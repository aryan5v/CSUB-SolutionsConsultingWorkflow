#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_ENV="${APP_ENV:-development}"
AWS_REGION="${AWS_REGION:-us-west-2}"
PLATFORM_STACK="${PLATFORM_STACK:-PlatformStack}"
FOUNDATION_STACK="${FOUNDATION_STACK:-ReviewFoundationStack}"
EXPECTED_CATALOG_ROWS="${EXPECTED_CATALOG_ROWS:-982}"
RELEASE_PARAMETER_PREFIX="${RELEASE_PARAMETER_PREFIX:-/vetted/deploy/${APP_ENV}}"
OPERATION="${1:-}"
RELEASE_SHA="${2:-}"
BUNDLE="${3:-}"
PLAN="$ROOT/artifacts/deploy/change-sets.tsv"

if [[ "$OPERATION" != "deploy" && "$OPERATION" != "dry-run" && "$OPERATION" != "rollback" ]]; then
  echo "usage: run_release.sh <deploy|dry-run|rollback> <sha> [bundle-directory]" >&2
  exit 64
fi
if [[ ! "$RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "release SHA must be a full lowercase commit SHA" >&2
  exit 64
fi

mkdir -p "$ROOT/artifacts/deploy"

if [[ "$OPERATION" != "rollback" ]]; then
  [[ -f "$BUNDLE/manifest.json" ]] || { echo "verified bundle is required" >&2; exit 64; }
  assembly="$BUNDLE/cloud-assembly"
  frontend="$BUNDLE/frontend"
  python3 "$ROOT/scripts/deploy/verify_release.py" --bundle "$BUNDLE" \
    --sha "$RELEASE_SHA" --extract-to "$BUNDLE"
fi

output() {
  aws cloudformation describe-stacks --stack-name "$PLATFORM_STACK" --region "$AWS_REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue | [0]" --output text
}

notify() {
  local stage="$1" rollback_status="$2"
  [[ -n "${ALERT_TOPIC_ARN:-}" ]] || return 0
  local run_url="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-unknown}/actions/runs/${GITHUB_RUN_ID:-unknown}"
  aws sns publish --topic-arn "$ALERT_TOPIC_ARN" --subject "VETTED deployment ${stage}" \
    --message "stage=${stage} sha=${RELEASE_SHA} run=${run_url} rollback=${rollback_status}" >/dev/null || true
}

canary() {
  python3 "$ROOT/scripts/deploy/smoke_release.py" \
    --cloudfront-domain "$(output CloudFrontDomain)" \
    --api-endpoint "$(output ApiEndpoint)" \
    --cognito-client-id "$(output UserPoolClientId)" \
    --lambda-name "csub-case-proxy-${APP_ENV}" \
    --expected-sha "$1" --expected-catalog-rows "$EXPECTED_CATALOG_ROWS"
}

previous="$(aws ssm get-parameter --name "${RELEASE_PARAMETER_PREFIX}/last-good-sha" \
  --query Parameter.Value --output text 2>/dev/null || true)"
if [[ -n "$previous" && ! "$previous" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Invalid last-known-good release pointer" >&2
  exit 2
fi

if [[ "$OPERATION" == "rollback" ]]; then
  rollback_dir="${RUNNER_TEMP:-/tmp}/vetted-explicit-rollback"
  rollback_status=0
  "$ROOT/scripts/deploy/download_release.sh" "$RELEASE_SHA" "$rollback_dir" --require-healthy || rollback_status=$?
  if [[ $rollback_status -eq 0 ]]; then
    "$ROOT/scripts/deploy/record_release_state.sh" "$RELEASE_SHA" ROLLBACK_STARTED "$previous" "explicit" || rollback_status=$?
    "$ROOT/scripts/deploy/deploy_stacks.sh" --operation recovery --release-sha "$RELEASE_SHA" \
      --assembly "$rollback_dir/cloud-assembly" || rollback_status=$?
    "$ROOT/scripts/deploy/promote_frontend.sh" "$rollback_dir/frontend" || rollback_status=$?
    canary "$RELEASE_SHA" || rollback_status=$?
  fi
  if [[ $rollback_status -eq 0 ]]; then
    "$ROOT/scripts/deploy/record_release_state.sh" "$RELEASE_SHA" HEALTHY "$previous" "explicit rollback verified"
    aws ssm put-parameter --name "${RELEASE_PARAMETER_PREFIX}/last-good-sha" --type String \
      --overwrite --value "$RELEASE_SHA" >/dev/null
    exit 0
  fi
  "$ROOT/scripts/deploy/record_release_state.sh" "$RELEASE_SHA" ROLLBACK_FAILED "$previous" "explicit recovery failed" || true
  notify CRITICAL failed
  exit "$rollback_status"
fi

"$ROOT/scripts/deploy/deploy_stacks.sh" --operation preflight --release-sha "$RELEASE_SHA" \
  --assembly "$assembly" --plan "$PLAN"
cleanup_plan() {
  "$ROOT/scripts/deploy/deploy_stacks.sh" --operation cleanup --release-sha "$RELEASE_SHA" \
    --assembly "$assembly" --plan "$PLAN" >/dev/null 2>&1 || true
}
trap cleanup_plan EXIT
trap 'exit 130' INT TERM

if [[ "$OPERATION" == "dry-run" ]]; then
  cleanup_plan
  trap - EXIT INT TERM
  echo "Dry run passed: every stack was inspected and no change set was executed."
  exit 0
fi

"$ROOT/scripts/deploy/archive_release.sh" "$RELEASE_SHA" "$BUNDLE" >/dev/null
"$ROOT/scripts/deploy/record_release_state.sh" "$RELEASE_SHA" PREPARED "$previous" "all change sets guarded"
aws ssm put-parameter --name "${RELEASE_PARAMETER_PREFIX}/candidate-sha" --type String \
  --overwrite --value "$RELEASE_SHA" >/dev/null

status=0
"$ROOT/scripts/deploy/record_release_state.sh" "$RELEASE_SHA" DEPLOYING "$previous" "infrastructure"
"$ROOT/scripts/deploy/deploy_stacks.sh" --operation execute --release-sha "$RELEASE_SHA" \
  --assembly "$assembly" --plan "$PLAN" || status=$?
if [[ $status -eq 0 ]]; then
  "$ROOT/scripts/deploy/promote_frontend.sh" "$frontend" || status=$?
fi
if [[ $status -eq 0 ]]; then
  canary "$RELEASE_SHA" || status=$?
fi

if [[ $status -eq 0 ]]; then
  "$ROOT/scripts/deploy/record_release_state.sh" "$RELEASE_SHA" HEALTHY "$previous" "all canaries passed"
  aws ssm put-parameter --name "${RELEASE_PARAMETER_PREFIX}/last-good-sha" --type String \
    --overwrite --value "$RELEASE_SHA" >/dev/null
  aws ssm put-parameter --name "${RELEASE_PARAMETER_PREFIX}/last-good-run" --type String \
    --overwrite --value "${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-unknown}/actions/runs/${GITHUB_RUN_ID:-local}" >/dev/null
  echo "VETTED release $RELEASE_SHA is healthy."
  exit 0
fi

"$ROOT/scripts/deploy/record_release_state.sh" "$RELEASE_SHA" FAILED "$previous" "deployment or canary failed"
if [[ -z "$previous" || "$previous" == "$RELEASE_SHA" ]]; then
  notify FAILED unavailable
  echo "Release failed and no distinct healthy rollback target is recorded." >&2
  exit "$status"
fi

rollback_dir="${RUNNER_TEMP:-/tmp}/vetted-automatic-rollback"
rollback_infra=0
rollback_frontend=0
rollback_canary=0
unsafe_stack_status=""
for stack in "$FOUNDATION_STACK" "$PLATFORM_STACK"; do
  stack_status="$(aws cloudformation describe-stacks --stack-name "$stack" --region "$AWS_REGION" \
    --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo UNKNOWN)"
  case "$stack_status" in
    CREATE_COMPLETE|UPDATE_COMPLETE|UPDATE_ROLLBACK_COMPLETE) ;;
    *) unsafe_stack_status="${unsafe_stack_status}${stack}=${stack_status} " ;;
  esac
done
if "$ROOT/scripts/deploy/download_release.sh" "$previous" "$rollback_dir" --require-healthy; then
  "$ROOT/scripts/deploy/record_release_state.sh" "$RELEASE_SHA" ROLLBACK_STARTED "$previous" "automatic"
  if [[ -z "$unsafe_stack_status" ]]; then
    "$ROOT/scripts/deploy/deploy_stacks.sh" --operation recovery --release-sha "$previous" \
      --assembly "$rollback_dir/cloud-assembly" || rollback_infra=$?
  else
    rollback_infra=1
    echo "Unsafe CloudFormation state; refusing blind retry: $unsafe_stack_status" >&2
  fi
  # Restore the UI even when infrastructure recovery fails; this maximizes the
  # chance that the last healthy user experience remains available.
  "$ROOT/scripts/deploy/promote_frontend.sh" "$rollback_dir/frontend" || rollback_frontend=$?
  if [[ $rollback_infra -eq 0 && $rollback_frontend -eq 0 ]]; then
    canary "$previous" || rollback_canary=$?
  else
    rollback_canary=1
  fi
else
  rollback_infra=1
  rollback_frontend=1
  rollback_canary=1
fi

if [[ $rollback_infra -eq 0 && $rollback_frontend -eq 0 && $rollback_canary -eq 0 ]]; then
  "$ROOT/scripts/deploy/record_release_state.sh" "$RELEASE_SHA" ROLLED_BACK "$previous" "last-known-good verified"
  aws ssm put-parameter --name "${RELEASE_PARAMETER_PREFIX}/candidate-sha" --type String \
    --overwrite --value "$previous" >/dev/null
  notify FAILED succeeded
else
  "$ROOT/scripts/deploy/record_release_state.sh" "$RELEASE_SHA" ROLLBACK_FAILED "$previous" \
    "infra=${rollback_infra} frontend=${rollback_frontend} canary=${rollback_canary}"
  notify CRITICAL failed
  echo "CRITICAL: release and automatic rollback both failed; stop and recover through SSO." >&2
fi
exit "$status"
