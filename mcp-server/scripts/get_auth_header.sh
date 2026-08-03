#!/bin/sh
# Logs in to ReqTrackManager and prints a fresh MCP connection header as
# JSON on stdout: {"Authorization": "Bearer <access_token>"}.
#
# Written for Claude Code's `headersHelper` mechanism (see docs/mcp-server.md
# and https://code.claude.com/docs/en/mcp#use-dynamic-headers-for-custom-
# authentication): Claude Code runs this command fresh on every connection
# and reconnect, and automatically re-runs it and retries once if a tool
# call comes back 401/403 — which solves this app's access tokens being
# short-lived (12h by default) without needing a separate long-lived token
# mechanism. Point a Claude Code `.mcp.json` entry's `headersHelper` at this
# script instead of hardcoding a token that will eventually expire.
#
# Requires a NATIVE (non-SSO) account with 2FA disabled — this script does
# a single non-interactive password login, which can't complete a 2FA
# challenge or an OIDC redirect flow. Create a dedicated account for this
# purpose if you don't want to use a real person's credentials here (its
# access is scoped by its own real ReqTrackManager role, same as any other
# account — see docs/mcp-server.md's "Authentication model" section).
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
