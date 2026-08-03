FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
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

HEALTHCHECK --interval=10s --timeout=5s --retries=10 \
    CMD curl -f http://localhost:8100/health || exit 1

CMD ["python", "server.py"]
