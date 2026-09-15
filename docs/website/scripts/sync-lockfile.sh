#!/usr/bin/env bash
# Regenerates and verifies docs/website/package-lock.json under the Node
# version pinned in docs/website/.nvmrc, which matches
# .github/workflows/ci.yml's docs job. Mirrors frontend/scripts/sync-lockfile.sh
# (see that script's own comment for why this matters: a locally-installed
# Node on a different major version bundles a different npm major version,
# which can resolve transitive optional dependencies differently and
# silently write a package-lock.json that installs fine locally but fails
# CI's `npm ci` with "Missing: <pkg> from lock file").
#
# Run this after any change to docs/website/package.json (adding, removing,
# or bumping a dependency) before committing package-lock.json. Extra
# arguments are passed through to `npm install`, e.g.:
#   docs/website/scripts/sync-lockfile.sh some-new-package@1.2.3
set -euo pipefail
cd "$(dirname "$0")/.."

REQUIRED_NODE_MAJOR="$(cat .nvmrc)"
ACTUAL_NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
if [[ "$ACTUAL_NODE_MAJOR" != "$REQUIRED_NODE_MAJOR" ]]; then
  echo "error: active Node is $(node -v), but .nvmrc pins Node $REQUIRED_NODE_MAJOR (matches CI)." >&2
  echo "Run 'nvm use' in docs/website/ first (or otherwise switch to Node $REQUIRED_NODE_MAJOR), then retry." >&2
  exit 1
fi

rm -rf node_modules
npm install "$@"
rm -rf node_modules
npm ci
echo "package-lock.json regenerated and verified with npm ci under Node $(node -v)."
