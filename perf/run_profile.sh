#!/bin/sh
# Portable entry point for the performance profile (see perf/README.md). POSIX sh plus Python 3.9+ and Docker
# Compose; nothing else is needed, so it works on a bare Raspberry Pi.
#
#   perf/run_profile.sh <host-label> [--quick | --full] [--plan] [--cleanup] [options]
#
# --plan prints what would be created and what will not be touched, and starts nothing: read it before the first
# real run on a host that also serves production.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
for python in python3 python; do
    if command -v "$python" >/dev/null 2>&1; then
        exec "$python" "$here/run_profile.py" "$@"
    fi
done
echo "error: Python 3.9 or newer is required" >&2
exit 2
