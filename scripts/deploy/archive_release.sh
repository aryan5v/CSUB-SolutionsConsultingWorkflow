#!/usr/bin/env bash
set -euo pipefail

PLATFORM_STACK="${PLATFORM_STACK:-PlatformStack}"
AWS_REGION="${AWS_REGION:-us-west-2}"
RELEASE_SHA="${1:-}"
BUNDLE="${2:-}"

if [[ ! "$RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]] || [[ ! -f "$BUNDLE/manifest.json" ]]; then
  echo "usage: archive_release.sh <full-git-sha> <bundle-directory>" >&2
  exit 64
fi
jq -e --arg sha "$RELEASE_SHA" '.release_sha == $sha' "$BUNDLE/manifest.json" >/dev/null

bucket="$(aws cloudformation describe-stacks --stack-name "$PLATFORM_STACK" --region "$AWS_REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='FrontendBucketName'].OutputValue | [0]" --output text)"
prefix="_releases/${RELEASE_SHA}"

if aws s3api head-object --bucket "$bucket" --key "$prefix/manifest.json" >/dev/null 2>&1; then
  remote="$(mktemp)"
  trap 'rm -f "$remote"' EXIT
  aws s3api get-object --bucket "$bucket" --key "$prefix/manifest.json" "$remote" >/dev/null
  cmp -s "$BUNDLE/manifest.json" "$remote" || {
    echo "Release $RELEASE_SHA already exists with a different manifest" >&2
    exit 3
  }
  echo "Immutable release $RELEASE_SHA already archived with identical checksums."
  exit 0
fi

for artifact in cloud-assembly.tar.gz frontend.tar.gz; do
  digest="$(jq -r --arg name "$artifact" '.artifacts[$name].sha256' "$BUNDLE/manifest.json")"
  actual_digest="$(sha256sum "$BUNDLE/$artifact" | awk '{print $1}')"
  if [[ "$actual_digest" != "$digest" ]]; then
    echo "Release artifact checksum mismatch for $artifact: expected $digest, got $actual_digest" >&2
    exit 3
  fi
  if existing="$(aws s3api head-object --bucket "$bucket" --key "$prefix/$artifact" \
    --query 'Metadata.sha256' --output text 2>/dev/null)"; then
    [[ "$existing" == "$digest" ]] || {
      echo "Existing $artifact has a different checksum" >&2
      exit 3
    }
  else
    aws s3api put-object --bucket "$bucket" --key "$prefix/$artifact" \
      --body "$BUNDLE/$artifact" --metadata "sha256=$digest" --if-none-match '*' >/dev/null
  fi
done
# The manifest is the commit marker and is always written last.
aws s3api put-object --bucket "$bucket" --key "$prefix/manifest.json" \
  --body "$BUNDLE/manifest.json" --content-type application/json --if-none-match '*' >/dev/null
echo "$bucket"
