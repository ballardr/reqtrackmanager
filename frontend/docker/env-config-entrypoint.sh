#!/bin/sh
# Writes the runtime API base URL into env-config.js from the
# VITE_API_BASE_URL environment variable, so the same built image can be
# pointed at different backends without a rebuild (I-A-01: loosely coupled).
#
# `${VITE_API_BASE_URL-default}` (no colon) is deliberate, not a typo: with
# a colon, `${VAR:-default}` treats an explicitly-set *empty* string the
# same as unset and substitutes the default anyway, which would silently
# break the same-origin subpath deployment pattern (PUBLIC_API_BASE_URL=
# left empty on purpose, meaning "same origin, use relative API paths" —
# see docs/deployment.md's "Same-origin subpath deployment" section). The
# no-colon form only falls back when the variable is truly unset, which is
# what "no default was configured" actually means here.
set -eu

cat > /usr/share/nginx/html/env-config.js <<EOF
window.__ENV__ = {
  VITE_API_BASE_URL: "${VITE_API_BASE_URL-http://localhost:8000}"
};
EOF

exec nginx -g "daemon off;"
