#!/usr/bin/env bash
set -euo pipefail

PLATFORM_STACK="${PLATFORM_STACK:-PlatformStack}"
AWS_REGION="${AWS_REGION:-us-west-2}"
RELEASE_SHA="${1:-}"
STATE="${2:-}"
PREVIOUS_SHA="${3:-}"
DETAIL="${4:-}"

if [[ ! "$RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]] || [[ ! "$STATE" =~ ^[A-Z_]+$ ]]; then
  echo "usage: record_release_state.sh <sha> <STATE> [previous-sha] [safe-detail]" >&2
  exit 64
fi
bucket="$(aws cloudformation describe-stacks --stack-name "$PLATFORM_STACK" --region "$AWS_REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='FrontendBucketName'].OutputValue | [0]" --output text)"
run_id="${GITHUB_RUN_ID:-local}"
attempt="${GITHUB_RUN_ATTEMPT:-1}"
timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
document="$(mktemp)"
trap 'rm -f "$document"' EXIT
jq -n --arg sha "$RELEASE_SHA" --arg state "$STATE" --arg previous "$PREVIOUS_SHA" \
  --arg detail "$DETAIL" --arg run_id "$run_id" --arg attempt "$attempt" \
  --arg actor "${GITHUB_ACTOR:-local}" --arg timestamp "$timestamp" \
  '{schema_version:1,release_sha:$sha,state:$state,previous_release:$previous,detail:$detail,run_id:$run_id,run_attempt:$attempt,actor:$actor,recorded_at:$timestamp}' \
  >"$document"
key="_deployment-state/${RELEASE_SHA}/${run_id}-${attempt}-${STATE}.json"
if aws s3api head-object --bucket "$bucket" --key "$key" >/dev/null 2>&1; then
  echo "Release state $STATE was already recorded for this run."
  exit 0
fi
aws s3api put-object --bucket "$bucket" --key "$key" --body "$document" \
  --content-type application/json --if-none-match '*' >/dev/null

if [[ "$STATE" == "HEALTHY" ]]; then
  healthy_key="_releases/${RELEASE_SHA}/healthy.json"
  if ! aws s3api head-object --bucket "$bucket" --key "$healthy_key" >/dev/null 2>&1; then
    aws s3api put-object --bucket "$bucket" --key "$healthy_key" --body "$document" \
      --content-type application/json --if-none-match '*' >/dev/null
  fi
  aws s3api head-object --bucket "$bucket" --key "$healthy_key" >/dev/null
fi
