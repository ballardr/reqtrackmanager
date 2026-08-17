#!/usr/bin/env bash
# Regenerates and verifies frontend/package-lock.json under the Node version
# pinned in frontend/.nvmrc, which matches .github/workflows/ci.yml and
# frontend/Dockerfile.
#
# Why this matters: a locally-installed Node on a different major version
# bundles a different npm major version, which can resolve transitive
# optional dependencies differently and silently write a package-lock.json
# that installs fine locally but fails CI's `npm ci` with "Missing: <pkg>
# from lock file". See docs/decisions.md ("PR #8 CI failure...").
#
# Run this after any change to frontend/package.json (adding, removing, or
# bumping a dependency) before committing package-lock.json. Extra
# arguments are passed through to `npm install`, e.g.:
#   frontend/scripts/sync-lockfile.sh some-new-package@1.2.3
set -euo pipefail
cd "$(dirname "$0")/.."

REQUIRED_NODE_MAJOR="$(cat .nvmrc)"
ACTUAL_NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
if [[ "$ACTUAL_NODE_MAJOR" != "$REQUIRED_NODE_MAJOR" ]]; then
  echo "error: active Node is $(node -v), but .nvmrc pins Node $REQUIRED_NODE_MAJOR (matches CI/Dockerfile)." >&2
  echo "Run 'nvm use' in frontend/ first (or otherwise switch to Node $REQUIRED_NODE_MAJOR), then retry." >&2
  exit 1
fi

rm -rf node_modules
npm install "$@"
rm -rf node_modules
npm ci
echo "package-lock.json regenerated and verified with npm ci under Node $(node -v)."
