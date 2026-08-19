FROM python:3.12-slim

# Build identity (GET /api/v1/system/version, app/version.py): supplied via
# --build-arg by the docker-build CI job, which already computes a
# GitVersion SemVer and knows the commit SHA for image tagging but
# previously had no way to surface either from inside a running container.
# Defaults keep a plain local `docker build` (no --build-arg) working, just
# reporting placeholder values instead of failing.
ARG APP_VERSION=dev
ARG GIT_SHA=unknown
ARG BUILD_DATE=unknown
ENV APP_VERSION=${APP_VERSION} \
    GIT_SHA=${GIT_SHA} \
    BUILD_DATE=${BUILD_DATE}

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Hardening review: ran as root with no reason to. /app/data/files is
# created ahead of the local-storage volume mount below so a fresh named
# volume inherits the right ownership from the image (Docker copies the
# mount point's existing content/permissions into a brand-new named volume
# on first use) — an *existing* volume from a previous root-owned run will
# still be root-owned and need a one-time `chown` after upgrading, same as
# this project's other pre-release "reset and reseed" upgrade path.
RUN useradd --system --create-home --home-dir /home/app app \
    && mkdir -p /app/data/files \
    && chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=10 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
