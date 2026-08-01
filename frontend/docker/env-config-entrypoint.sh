#!/bin/sh
# Writes the runtime API base URL into env-config.js from the
# VITE_API_BASE_URL environment variable, so the same built image can be
# pointed at different backends without a rebuild (I-A-01: loosely coupled).
set -eu

cat > /usr/share/nginx/html/env-config.js <<EOF
window.__ENV__ = {
  VITE_API_BASE_URL: "${VITE_API_BASE_URL:-http://localhost:8000}"
};
EOF

exec nginx -g "daemon off;"
