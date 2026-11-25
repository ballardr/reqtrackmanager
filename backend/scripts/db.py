"""
Module: scripts.db

Developer wrapper around Alembic's CLI commands (`revision`, `upgrade`, `downgrade`, `current`, `history`, `heads`).

Design decisions:
- Alembic reads `version_locations` from the static `alembic.ini` before `alembic/env.py` runs, so a bare `alembic upgrade
  head` would see only `backend/alembic/versions/` and silently ignore every module's `migrations_dir`. This script builds
  the `Config` in Python, calls `app.modules.registry.configure_alembic_version_locations(cfg)` (as
  `app.migrations.run_migrations` does at boot) and then calls the real `alembic.command.*`.
- It does not use `alembic.config.CommandLine`, which builds its own `Config` before that call could be made.
- `revision` without `--autogenerate` writes a blank revision into the core `backend/alembic/versions/`; write the body in
  the raw-SQL, `IF NOT EXISTS` style of the existing migrations and, for a module migration, `git mv` it into the module's
  `migrations_dir` before committing (only `down_revision` matters, not the directory).

Usage (from `backend/`, venv active):

    python scripts/db.py revision -m "add compliance mapping tables"
    python scripts/db.py revision -m "add a column" --autogenerate
    python scripts/db.py upgrade head
    python scripts/db.py upgrade +1
    python scripts/db.py downgrade -1
    python scripts/db.py current
    python scripts/db.py history
    python scripts/db.py heads
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
# Equivalent of `alembic.ini`'s `prepend_sys_path = .`: this script does not go through Alembic's bootstrapping, so it
# makes `app` importable itself, whatever the working directory.
sys.path.insert(0, str(_BACKEND_DIR))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.modules.registry import configure_alembic_version_locations  # noqa: E402


def _build_config() -> Config:
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    configure_alembic_version_locations(cfg)
    return cfg


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    revision_parser = subparsers.add_parser("revision", help="Create a new revision file.")
    revision_parser.add_argument("-m", "--message", required=True, help="Revision message.")
    revision_parser.add_argument(
        "--autogenerate", action="store_true", help="Autogenerate the revision body from model/schema diffs."
    )

    upgrade_parser = subparsers.add_parser("upgrade", help="Apply migrations.")
    upgrade_parser.add_argument("target", nargs="?", default="head", help="Target revision (default: head).")

    downgrade_parser = subparsers.add_parser("downgrade", help="Revert migrations.")
    downgrade_parser.add_argument("target", help="Target revision (e.g. -1, or a specific revision id).")

    subparsers.add_parser("current", help="Show the current revision(s).")
    subparsers.add_parser("history", help="Show the full revision chain, across every configured location.")
    subparsers.add_parser("heads", help="Show the current head(s) of the chain.")

    args = parser.parse_args(argv)
    cfg = _build_config()

    if args.subcommand == "revision":
        command.revision(cfg, message=args.message, autogenerate=args.autogenerate)
    elif args.subcommand == "upgrade":
        command.upgrade(cfg, args.target)
    elif args.subcommand == "downgrade":
        command.downgrade(cfg, args.target)
    elif args.subcommand == "current":
        command.current(cfg)
    elif args.subcommand == "history":
        command.history(cfg)
    elif args.subcommand == "heads":
        command.heads(cfg)


if __name__ == "__main__":
    main(sys.argv[1:])
