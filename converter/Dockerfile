# Picture converter: runs Ghostscript and poppler on uploaded EPS and PDF logos, away from the backend.
# Nothing here but the two tools and converter.py; Compose runs it with no network beyond an internal one shared
# with the backend, no secrets, a read-only filesystem and no Linux capabilities (see docs/solution-architecture.md).
FROM python:3.15-slim

# fonts-urw-base35: the standard PostScript fonts (Helvetica, Times) an EPS often names without embedding them.
# zlib1g is named so the patched release replaces the one the base image ships (CVE-2026-76844, CVE-2026-85091).
RUN apt-get update && apt-get install -y --no-install-recommends ghostscript poppler-utils fonts-urw-base35 zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --no-create-home --uid 10001 converter

WORKDIR /srv
COPY converter.py .
COPY tests ./tests

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER converter
EXPOSE 8300

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8300/health', timeout=4)"]

CMD ["python", "converter.py"]
