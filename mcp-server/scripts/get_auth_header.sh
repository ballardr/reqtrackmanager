#!/bin/sh
# Logs in to ReqTrackManager and prints a fresh MCP connection header as
# JSON on stdout: {"Authorization": "Bearer <access_token>"}.
#
# For Claude Code's `headersHelper` mechanism (docs/mcp-server.md): Claude Code runs this on every connection and
# reconnect, and re-runs it once if a tool call returns 401/403, so the short-lived access token (12h by default)
# is refreshed without a long-lived token. Point a `.mcp.json` entry's `headersHelper` at this script.
#
# Requires a native (non-SSO) account with 2FA disabled: this is one non-interactive password login, which cannot
# complete a 2FA challenge or an OIDC redirect. Use a dedicated account if a person's credentials should not be used;
# its access is scoped by its own role (docs/mcp-server.md, "Authentication model").
#
# Required environment variables:
#   REQTRACK_EMAIL    - the account's email
#   REQTRACK_PASSWORD - the account's password
# Optional:
#   REQTRACK_URL       - the backend's base URL (default http://localhost:8000)
set -eu

REQTRACK_URL="${REQTRACK_URL:-http://localhost:8000}"
: "${REQTRACK_EMAIL:?Set REQTRACK_EMAIL to the login account's email}"
: "${REQTRACK_PASSWORD:?Set REQTRACK_PASSWORD to the login account's password}"

response=$(curl -sf -X POST "$REQTRACK_URL/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"${REQTRACK_EMAIL}\",\"password\":\"${REQTRACK_PASSWORD}\"}")

python3 -c '
import json
import sys

body = json.load(sys.stdin)
token = body.get("access_token")
if not token:
    sys.stderr.write(
        "Login succeeded but returned no access_token — this account likely has 2FA enabled, "
        "which this non-interactive script cannot complete. Use a native account with 2FA "
        "disabled, or set a static (eventually-expiring) token directly instead of headersHelper.\n"
    )
    sys.exit(1)
print(json.dumps({"Authorization": f"Bearer {token}"}))
' <<EOF
$response
EOF
