"""
Module: version

Exposes the running backend's build identity: semantic version, commit SHA and build timestamp.

Design decisions:
- The values are baked into the image at build time through Docker build ARGs (`backend/Dockerfile`, the `docker-build`
  job in `.github/workflows/ci.yml`) and read once at import time from the environment.
- A local run (`uvicorn app.main:app`, the dev/test Compose stack) sets none of them, so placeholders are used instead of
  raising: this is display-only metadata, not a required setting.
"""

from __future__ import annotations

import os

APP_VERSION = os.environ.get("APP_VERSION", "dev")
GIT_SHA = os.environ.get("GIT_SHA", "unknown")
BUILD_DATE = os.environ.get("BUILD_DATE", "unknown")
