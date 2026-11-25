# Stages: `base` (application code and dependencies), `backup` (base plus the disaster-recovery tools), `profile`
# (base plus the profilers, for developers) and `backend`, the last stage and so the default target, which is the API image every existing build produces.
FROM python:3.15-slim AS base

# Build identity (GET /api/v1/system/version, app/version.py) is supplied through --build-arg by the
# docker-build CI job, which holds the GitVersion SemVer and the commit SHA. The defaults keep a plain
# local `docker build` working, reporting placeholder values.
ARG APP_VERSION=dev
ARG GIT_SHA=unknown
ARG BUILD_DATE=unknown
ENV APP_VERSION=${APP_VERSION} \
    GIT_SHA=${GIT_SHA} \
    BUILD_DATE=${BUILD_DATE}

WORKDIR /app

# EPS and PDF logos are converted by the separate converter service (../converter), not by tools in this image.
# zlib1g and libzstd1 are named so the patched releases replace the ones the base image ships.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl zlib1g libzstd1 \
    && rm -rf /var/lib/apt/lists/*

# pip is removed once the dependencies are installed: the base image's pip vendors msgpack, urllib3 and setuptools
# copies that Trivy flags (HIGH), and no release of pip is free of them. A derived image that installs a module
# package restores it first with `python -m ensurepip` (docs/modules.md).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y pip

COPY . .

# The application runs as a non-root user. /app/data/files is created before the local-storage volume
# mount so a fresh named volume inherits its ownership from the image (Docker copies the mount point's
# permissions into a new named volume on first use); a volume created by a root-owned image keeps root
# ownership and needs a one-time `chown`.
RUN useradd --system --create-home --home-dir /home/app app \
    && mkdir -p /app/data/files /demo/state /demo/status \
    && chmod +x /app/docker-entrypoint.sh \
    && chown -R app:app /app /demo
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

# Developer profiling image (docker-compose.profile.yml, perf/README.md): the application image plus memray (heap
# profiler) and py-spy (sampling CPU profiler). Built only with `--target profile`, never published and never part of
# the production compose path. Both tools attach to or wrap the Python process, so they stay out of the API image.
# /profile is created here so a fresh named volume inherits the app user's ownership.
FROM base AS profile
USER root
RUN python -m ensurepip \
    && python -m pip install --no-cache-dir memray==1.20.0 py-spy==0.4.2 \
    && mkdir -p /profile && chown app:app /profile \
    && chmod +x /app/scripts/profile_entrypoint.sh
USER app
CMD ["./scripts/profile_entrypoint.sh"]

FROM base AS backend
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=120s --retries=10 \
    CMD curl -f http://127.0.0.1:8000/health || exit 1

# Multi-worker uvicorn plus Prometheus multi-process setup — see the script.
CMD ["./docker-entrypoint.sh"]
