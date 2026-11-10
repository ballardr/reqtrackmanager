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

# Optional Microsoft Clarity project id (a demonstration deployment only). Only a short alphanumeric value is
# written into the JavaScript file; anything else is ignored, so the value cannot inject script.
CLARITY_PROJECT_ID_CHECKED=""
case "${CLARITY_PROJECT_ID-}" in
  "") ;;
  *[!A-Za-z0-9]*) echo "CLARITY_PROJECT_ID ignored: it must contain letters and digits only." >&2 ;;
  *) CLARITY_PROJECT_ID_CHECKED="${CLARITY_PROJECT_ID}" ;;
esac

cat > /usr/share/nginx/html/env-config.js <<EOF
window.__ENV__ = {
  VITE_API_BASE_URL: "${VITE_API_BASE_URL-http://localhost:8000}",
  CLARITY_PROJECT_ID: "${CLARITY_PROJECT_ID_CHECKED}"
};
EOF

# --- Content-Security-Policy -----------------------------------------------------------------------------------
# Built here because it depends on the deployment. Every value that reaches the header is checked against a strict
# pattern first and dropped (with a message) otherwise, so an environment variable cannot add a directive or a quote.
origin_ok() { printf '%s' "$1" | grep -Eq '^https?://[A-Za-z0-9._-]+(:[0-9]{1,5})?$|^https?://\[[0-9A-Fa-f:]+\](:[0-9]{1,5})?$'; }

api_origin=""
case "${VITE_API_BASE_URL-http://localhost:8000}" in
  http://*|https://*)
    candidate="$(printf '%s' "${VITE_API_BASE_URL-}" | sed -E 's#^(https?://[^/]+).*#\1#')"
    if origin_ok "$candidate"; then api_origin="$candidate"; else echo "VITE_API_BASE_URL is not a plain origin; the content security policy allows only this site." >&2; fi ;;
esac

# Origins the operator lists (space or comma separated).
checked_origins() {
  for item in $(printf '%s' "$1" | tr ',' ' '); do
    if origin_ok "$item"; then printf '%s ' "$item"; else echo "Ignored $2 entry that is not a plain origin." >&2; fi
  done
}
extra_script="$(checked_origins "${CSP_SCRIPT_SRC_EXTRA-}" CSP_SCRIPT_SRC_EXTRA)"
frame_src="$(checked_origins "${MODULE_FRAME_ALLOWED_ORIGINS-}" MODULE_FRAME_ALLOWED_ORIGINS)"
[ -n "$frame_src" ] || frame_src="'none'"

ws_origin=""
case "$api_origin" in
  https://*) ws_origin="wss://${api_origin#https://}" ;;
  http://*) ws_origin="ws://${api_origin#http://}" ;;
esac

clarity_hosts=""
[ -z "$CLARITY_PROJECT_ID_CHECKED" ] || clarity_hosts="https://www.clarity.ms https://*.clarity.ms https://c.bing.com"

policy="default-src 'self'; script-src 'self' ${extra_script}${clarity_hosts}; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: ${api_origin} ${clarity_hosts}; font-src 'self' data:; connect-src 'self' ${api_origin} ${ws_origin} ${clarity_hosts}; media-src 'self' blob: ${api_origin}; worker-src 'self' blob:; frame-src ${frame_src}; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
printf 'add_header Content-Security-Policy "%s" always;\n' "$policy" > /var/cache/nginx/content-security-policy.inc

exec nginx -g "daemon off;"
