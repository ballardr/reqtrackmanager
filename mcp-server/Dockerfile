FROM python:3.12-slim

WORKDIR /app

# zlib1g is named so the patched release replaces the one the base image ships (CVE-2026-76844, CVE-2026-85091).
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Hardening review: ran as root with no reason to — this service holds no
# credentials of its own, writes nothing to disk, and only ever relays
# requests, so there's no privileged operation here a non-root user would
# block.
RUN useradd --system --create-home --home-dir /home/mcp mcp && chown -R mcp:mcp /app
USER mcp

EXPOSE 8100

HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=10 \
    CMD curl -f http://127.0.0.1:8100/health || exit 1

CMD ["python", "server.py"]
