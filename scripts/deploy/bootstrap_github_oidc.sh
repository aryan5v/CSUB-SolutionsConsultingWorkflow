#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AWS_REGION="${AWS_REGION:-us-west-2}"
STACK_NAME="${CICD_BOOTSTRAP_STACK:-VettedGitHubOidc}"
: "${GITHUB_ORGANIZATION:?set GITHUB_ORGANIZATION to the GitHub owner}"
: "${GITHUB_REPOSITORY:?set GITHUB_REPOSITORY to the repository name}"
GITHUB_ENVIRONMENT="${GITHUB_ENVIRONMENT:-production}"
APP_ENV="${APP_ENV:-development}"
FOUNDATION_STACK="${FOUNDATION_STACK:-ReviewFoundationStack}"
PLATFORM_STACK="${PLATFORM_STACK:-PlatformStack}"
GITHUB_DEPLOY_ROLE_NAME="${GITHUB_DEPLOY_ROLE_NAME:-vetted-github-deploy}"
DEPLOYMENT_ALERT_TOPIC_NAME="${DEPLOYMENT_ALERT_TOPIC_NAME:-vetted-deployment-alerts}"

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
for output_name in frontend_bucket cloudfront_domain; do
  output_value="${!output_name}"
  if [[ -z "$output_value" || "$output_value" == "None" ]]; then
    echo "Missing required ${PLATFORM_STACK} output: ${output_name}" >&2
    exit 1
  fi
done
if [[ -z "$distribution_id" || "$distribution_id" == "None" ]]; then
  distribution_id="$(aws cloudfront list-distributions \
    --query "DistributionList.Items[?DomainName=='${cloudfront_domain}'].Id | [0]" --output text)"
fi
if [[ -z "$distribution_id" || "$distribution_id" == "None" ]]; then
  echo "Could not resolve the CloudFront distribution for ${cloudfront_domain}" >&2
  exit 1
fi
asset_bucket="$(aws cloudformation describe-stack-resource --stack-name CDKToolkit \
  --logical-resource-id StagingBucket --region "$AWS_REGION" \
  --query StackResourceDetail.PhysicalResourceId --output text)"
if [[ -z "$asset_bucket" || "$asset_bucket" == "None" ]]; then
  echo "Could not resolve the CDKToolkit staging bucket" >&2
  exit 1
fi

aws cloudformation deploy --stack-name "$STACK_NAME" \
  --template-file "$ROOT/infra/cicd/github-oidc-role.yml" \
  --capabilities CAPABILITY_NAMED_IAM --region "$AWS_REGION" \
  --no-fail-on-empty-changeset --parameter-overrides \
    "GitHubOrganization=$GITHUB_ORGANIZATION" \
    "GitHubRepository=$GITHUB_REPOSITORY" \
    "GitHubOwnerId=$owner_id" \
    "GitHubRepositoryId=$repo_id" \
    "GitHubEnvironment=$GITHUB_ENVIRONMENT" \
    "GitHubDeployRoleName=$GITHUB_DEPLOY_ROLE_NAME" \
    "DeploymentAlertTopicName=$DEPLOYMENT_ALERT_TOPIC_NAME" \
    "ApplicationEnvironment=$APP_ENV" \
    "FoundationStackName=$FOUNDATION_STACK" \
    "PlatformStackName=$PLATFORM_STACK" \
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
