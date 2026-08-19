"""
Module: version

Exposes the running backend's own build identity: semantic version, commit
SHA, and build timestamp. These are baked into the container image at build
time via Docker build ARGs (see `backend/Dockerfile` and the `docker-build`
job in `.github/workflows/ci.yml`, which already computes a GitVersion
SemVer and tags images with it but previously had no way to surface that
same information from inside a running instance). Read once at import time
from the environment `ENV`-set by that Dockerfile.

Falls back to placeholder values for a local, non-Docker run (`uvicorn
app.main:app` directly, or the dev/test Compose stack, neither of which
sets these) rather than raising — this is display-only metadata, not a
required setting.
"""

from __future__ import annotations

import os

APP_VERSION = os.environ.get("APP_VERSION", "dev")
GIT_SHA = os.environ.get("GIT_SHA", "unknown")
BUILD_DATE = os.environ.get("BUILD_DATE", "unknown")
