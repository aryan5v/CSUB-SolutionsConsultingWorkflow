#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AWS_REGION="${AWS_REGION:-us-west-2}"
STACK_NAME="${CICD_BOOTSTRAP_STACK:-VettedGitHubOidc}"
GITHUB_ORGANIZATION="${GITHUB_ORGANIZATION:-aryan5v}"
GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-CSUB-SolutionsConsultingWorkflow}"
GITHUB_ENVIRONMENT="${GITHUB_ENVIRONMENT:-production}"
APP_ENV="${APP_ENV:-development}"
PLATFORM_STACK="${PLATFORM_STACK:-PlatformStack}"

repo_json="$(gh api "repos/${GITHUB_ORGANIZATION}/${GITHUB_REPOSITORY}")"
owner_id="$(jq -r '.owner.id' <<<"$repo_json")"
repo_id="$(jq -r '.id' <<<"$repo_json")"

# The environment itself is restricted to main. The OIDC token trust also uses
# immutable owner/repository IDs and the exact workflow ref.
gh api --method PUT "repos/${GITHUB_ORGANIZATION}/${GITHUB_REPOSITORY}/environments/${GITHUB_ENVIRONMENT}" \
  --input - <<'JSON'
{"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}
JSON
if ! gh api "repos/${GITHUB_ORGANIZATION}/${GITHUB_REPOSITORY}/environments/${GITHUB_ENVIRONMENT}/deployment-branch-policies" \
  --jq '.branch_policies[] | select(.name == "main") | .name' | grep -qx main; then
  gh api --method POST "repos/${GITHUB_ORGANIZATION}/${GITHUB_REPOSITORY}/environments/${GITHUB_ENVIRONMENT}/deployment-branch-policies" \
    -f name=main -f type=branch >/dev/null
fi
stack_output() {
  aws cloudformation describe-stacks --stack-name "$PLATFORM_STACK" --region "$AWS_REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue | [0]" --output text
}
frontend_bucket="$(stack_output FrontendBucketName)"
cloudfront_domain="$(stack_output CloudFrontDomain)"
distribution_id="$(stack_output CloudFrontDistributionId)"
if [[ -z "$distribution_id" || "$distribution_id" == "None" ]]; then
  distribution_id="$(aws cloudfront list-distributions \
    --query "DistributionList.Items[?DomainName=='${cloudfront_domain}'].Id | [0]" --output text)"
fi
asset_bucket="$(aws cloudformation describe-stack-resource --stack-name CDKToolkit \
  --logical-resource-id StagingBucket --region "$AWS_REGION" \
  --query StackResourceDetail.PhysicalResourceId --output text)"

aws cloudformation deploy --stack-name "$STACK_NAME" \
  --template-file "$ROOT/infra/cicd/github-oidc-role.yml" \
  --capabilities CAPABILITY_NAMED_IAM --region "$AWS_REGION" \
  --no-fail-on-empty-changeset --parameter-overrides \
    "GitHubOrganization=$GITHUB_ORGANIZATION" \
    "GitHubRepository=$GITHUB_REPOSITORY" \
    "GitHubOwnerId=$owner_id" \
    "GitHubRepositoryId=$repo_id" \
    "GitHubEnvironment=$GITHUB_ENVIRONMENT" \
    "ApplicationEnvironment=$APP_ENV" \
    "FrontendBucketName=$frontend_bucket" \
    "CloudFrontDistributionId=$distribution_id" \
    "CanaryFunctionName=csub-case-proxy-${APP_ENV}" \
    "BootstrapAssetBucketName=$asset_bucket"
aws cloudformation update-termination-protection --stack-name "$STACK_NAME" \
  --enable-termination-protection --region "$AWS_REGION" >/dev/null

# GitHub recommends updating the cloud trust before changing the token format.
# Immutable subjects automatically add owner/repository IDs to the repo segment.
gh api --method PUT "repos/${GITHUB_ORGANIZATION}/${GITHUB_REPOSITORY}/actions/oidc/customization/sub" \
  --input - <<'JSON'
{"use_default":false,"use_immutable_subject":true,"include_claim_keys":["context","workflow_ref"]}
JSON

aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" \
  --query 'Stacks[0].Outputs' --output json
