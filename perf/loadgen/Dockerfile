# The load generator image: Locust only, no application code. Built and run by the performance runner inside the
# throwaway `reqtrack-perf` Compose project; it can only reach the stack's own `backend` service (see run.py).
FROM python:3.12-slim

WORKDIR /loadgen
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --system --create-home --home-dir /home/loadgen loadgen
COPY run.py scenarios.py ./
USER loadgen
# One run per container: the request (scenario, users, duration, dataset manifest) arrives as JSON on stdin and the
# summary leaves as JSON on stdout, so no file or volume is shared with the host.
ENTRYPOINT ["python", "/loadgen/run.py"]
