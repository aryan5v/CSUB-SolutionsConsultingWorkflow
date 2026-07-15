#!/usr/bin/env bash
set -euo pipefail

PLATFORM_STACK="${PLATFORM_STACK:-PlatformStack}"
AWS_REGION="${AWS_REGION:-us-west-2}"
DIST="${1:-}"

if [[ ! -f "$DIST/index.html" ]] || [[ ! -d "$DIST/assets" ]]; then
  echo "usage: promote_frontend.sh <verified-dist-directory>" >&2
  exit 64
fi

output() {
  aws cloudformation describe-stacks --stack-name "$PLATFORM_STACK" \
    --region "$AWS_REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue | [0]" --output text
}

bucket="$(output FrontendBucketName)"
domain="$(output CloudFrontDomain)"
distribution_id="${CLOUDFRONT_DISTRIBUTION_ID:-$(output CloudFrontDistributionId)}"

# Vite assets are content-addressed. Retaining earlier hashes makes the index
# cutover safe for clients that loaded a previous version.
aws s3 sync "$DIST/assets/" "s3://${bucket}/assets/" \
  --cache-control "public,max-age=31536000,immutable"
aws s3 sync "$DIST/" "s3://${bucket}/" \
  --exclude "assets/*" --exclude "index.html" --exclude "_releases/*" \
  --exclude "_deployment-state/*" --cache-control "public,max-age=300"
aws s3 cp "$DIST/index.html" "s3://${bucket}/index.html" \
  --content-type "text/html; charset=utf-8" \
  --cache-control "no-cache,no-store,must-revalidate"

invalidation_id="$(aws cloudfront create-invalidation --distribution-id "$distribution_id" \
  --paths '/*' --query Invalidation.Id --output text)"
aws cloudfront wait invalidation-completed --distribution-id "$distribution_id" \
  --id "$invalidation_id"
echo "https://${domain}"
