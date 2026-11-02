"""
Module: perf.generate_dataset

Command line for the dataset generator (`backend/app/services/perf_dataset`). Runs inside the performance stack's
backend container, where the runner mounts this directory at `/perf` and sets `PERF_STACK=1`.

Responsibilities:
- `--key-only`: print the snapshot key for a spec on this image's schema (no database needed).
- Otherwise: read `datasets/profiles.yaml`, build the structure through the running backend's API, bulk-insert the
  records, and print the dataset manifest as JSON on stdout (progress goes to stderr).

Design decisions:
- Refuses to run unless `PERF_STACK=1` (the guard lives in the library, `build.require_perf_stack`), so running
  it by hand in a container that holds real data fails before anything is written.
- Credentials come from the container's environment (`SERVER_ADMIN_EMAIL`, `SERVER_ADMIN_PASSWORD`,
  `PERF_USER_PASSWORD`), never the command line, so they do not appear in a process list.

Dependencies: the backend image (`app.*`), PyYAML, httpx.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.environ.get("PERF_APP_DIR", "/app"))

import httpx  # noqa: E402
import yaml  # noqa: E402

DEFAULT_PROFILES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datasets", "profiles.yaml")
API = "http://127.0.0.1:8000"


def main(argv: list[str] | None = None) -> int:
    """Parses the command line and runs; returns the process exit status."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tier", required=True)
    parser.add_argument("--breadth", default="single")
    parser.add_argument("--density", default="typical")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--profiles", default=DEFAULT_PROFILES)
    parser.add_argument("--key-only", action="store_true", help="print the snapshot key and exit")
    args = parser.parse_args(argv)

    from app.services.perf_dataset.build import RefusedToRun, generate_dataset, require_perf_stack, schema_head
    from app.services.perf_dataset.spec import ProfileError, build_spec

    try:
        with open(args.profiles) as handle:
            spec = build_spec(yaml.safe_load(handle), tier=args.tier, breadth=args.breadth, density=args.density, seed=args.seed)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.key_only:
        print(spec.snapshot_key(schema_head()))
        return 0
    try:
        require_perf_stack()
    except RefusedToRun as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    from app.database import SessionLocal

    def say(line: str) -> None:
        print(line, file=sys.stderr, flush=True)

    db = SessionLocal()
    try:
        with httpx.Client(base_url=API, timeout=300) as client:
            manifest = generate_dataset(
                db, client, spec, admin_email=os.environ["SERVER_ADMIN_EMAIL"], admin_password=os.environ["SERVER_ADMIN_PASSWORD"],
                user_password=os.environ["PERF_USER_PASSWORD"], say=say,
            )
    finally:
        db.close()
    if manifest["integrity_problems"]:
        say("integrity problems: " + "; ".join(manifest["integrity_problems"]))
    json.dump(manifest, sys.stdout)
    return 1 if manifest["integrity_problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
