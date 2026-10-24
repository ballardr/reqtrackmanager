# Stages: `base` (application code and dependencies), `backup` (base plus the disaster-recovery tools) and
# `backend`, the last stage and so the default target, which is the API image every existing build produces.
FROM python:3.12-slim AS base

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
    && chmod +x /app/docker-entrypoint.sh \
    && chown -R app:app /app
USER app

# Disaster-recovery backup tool (scripts/dr_backup.py, docs/disaster-recovery.md): the application image plus
# pg_dump 16 (from the PostgreSQL project's repository, because a dump must be restorable by the server's
# own major version and Debian ships a newer one), restic, age and ssh (for SFTP destinations). Built with `--target backup`; has no
# listener, so nothing here needs IPv6.
FROM base AS backup
USER root
RUN apt-get update && apt-get install -y --no-install-recommends gnupg restic age openssh-client \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/postgresql.gpg \
    && . /etc/os-release \
    && echo "deb [signed-by=/usr/share/keyrings/postgresql.gpg] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-16 \
    && apt-get purge -y gnupg && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /backup/repo /backup/staging /backup/status \
    && chown -R app:app /backup
ENV BACKUP_PG_DUMP=/usr/lib/postgresql/16/bin/pg_dump
USER app
HEALTHCHECK NONE
ENTRYPOINT ["python", "scripts/dr_backup.py"]
CMD ["run"]

FROM base AS backend
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=120s --retries=10 \
    CMD curl -f http://127.0.0.1:8000/health || exit 1

# Multi-worker uvicorn plus Prometheus multi-process setup — see the script.
CMD ["./docker-entrypoint.sh"]
