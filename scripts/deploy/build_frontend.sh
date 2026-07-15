#!/usr/bin/env bash
set -euo pipefail

ROOT="${SOURCE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
RELEASE_SHA="${1:-}"

if [[ ! "$RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "usage: build_frontend.sh <full-git-sha>" >&2
  exit 64
fi

: "${VITE_API_BASE_URL:?VITE_API_BASE_URL is required}"
: "${VITE_COGNITO_DOMAIN:?VITE_COGNITO_DOMAIN is required}"
: "${VITE_COGNITO_CLIENT_ID:?VITE_COGNITO_CLIENT_ID is required}"
: "${VITE_COGNITO_REDIRECT_URI:?VITE_COGNITO_REDIRECT_URI is required}"
: "${VITE_COGNITO_LOGOUT_URI:?VITE_COGNITO_LOGOUT_URI is required}"
export VITE_REVIEW_DATA_MODE=live

(
  cd "$ROOT/apps/reviewer-web"
  npm ci
  npm run build
)

# Deliberately omit wall-clock time: the same commit and inputs must produce
# the same release marker and artifact digest.
node -e 'const fs=require("node:fs"); fs.writeFileSync(process.argv[1], JSON.stringify({sha:process.argv[2]})+"\n")' \
  "$ROOT/apps/reviewer-web/dist/release.json" "$RELEASE_SHA"
