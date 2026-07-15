#!/usr/bin/env bash
set -euo pipefail

PLATFORM_STACK="${PLATFORM_STACK:-PlatformStack}"
AWS_REGION="${AWS_REGION:-us-west-2}"
RELEASE_SHA="${1:-}"
DESTINATION="${2:-}"
REQUIRE_HEALTHY=false
[[ "${3:-}" == "--require-healthy" ]] && REQUIRE_HEALTHY=true

if [[ ! "$RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]] || [[ -z "$DESTINATION" ]]; then
  echo "usage: download_release.sh <full-git-sha> <destination> [--require-healthy]" >&2
  exit 64
fi
bucket="$(aws cloudformation describe-stacks --stack-name "$PLATFORM_STACK" --region "$AWS_REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='FrontendBucketName'].OutputValue | [0]" --output text)"
prefix="_releases/${RELEASE_SHA}"
if [[ "$REQUIRE_HEALTHY" == true ]]; then
  aws s3api head-object --bucket "$bucket" --key "$prefix/healthy.json" >/dev/null
  if aws s3api head-object --bucket "$bucket" --key "$prefix/revoked.json" >/dev/null 2>&1; then
    echo "release $RELEASE_SHA has been revoked and cannot be restored" >&2
    exit 4
  fi
fi
mkdir -p "$DESTINATION"
for artifact in manifest.json cloud-assembly.tar.gz frontend.tar.gz; do
  aws s3api get-object --bucket "$bucket" --key "$prefix/$artifact" \
    "$DESTINATION/$artifact" >/dev/null
done
python3 "$(dirname "${BASH_SOURCE[0]}")/verify_release.py" --bundle "$DESTINATION" \
  --sha "$RELEASE_SHA" --extract-to "$DESTINATION"
