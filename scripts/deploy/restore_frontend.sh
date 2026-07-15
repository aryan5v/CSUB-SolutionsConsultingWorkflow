#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RELEASE_SHA="${1:-}"
DESTINATION="${2:-}"

if [[ ! "$RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]] || [[ -z "$DESTINATION" ]]; then
  echo "usage: restore_frontend.sh <healthy-release-sha> <destination>" >&2
  exit 64
fi

"$ROOT/scripts/deploy/download_release.sh" "$RELEASE_SHA" "$DESTINATION" --require-healthy
"$ROOT/scripts/deploy/promote_frontend.sh" "$DESTINATION/frontend"
