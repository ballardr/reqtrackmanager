"""
Module: scripts.db

Thin developer-facing wrapper around Alembic's own CLI commands
(`revision`, `upgrade`, `downgrade`, `current`, `history`, `heads`) — added
in a compliance-module-plan.md Phase 11 follow-up, the moment a first-party
module's migration first moved out of the flat, shared
`backend/alembic/versions/` directory into its own `migrations_dir`
(`app.modules.compliance.migrations/`, colocated with the rest of that
module's own code).

**Why this exists at all, rather than developers continuing to type bare
`alembic <command>` from `backend/`:** Alembic reads `version_locations`
from `alembic.ini` (a static file) to build its `ScriptDirectory` *before*
`alembic/env.py` ever runs — by the time any of this project's own Python
code could react to which modules are registered, Alembic has already
decided which directories it's going to scan for revision files. A bare
`alembic upgrade head` using this repo's own `alembic.ini` directly would
therefore only ever see `backend/alembic/versions/`, silently missing every
first-party module's own `migrations_dir` entirely — not erroring, just
quietly treating the module's migrations as if they didn't exist. This
script closes that gap the same way `app.migrations.run_migrations` (the
boot-time equivalent) already does: build a `Config` object in Python,
call `app.modules.registry.configure_alembic_version_locations(cfg)` on it
(which enumerates every registered module's own `migrations_dir` from the
*live* registry, not a hand-maintained list), and only then hand that fully
configured `Config` to the real `alembic.command.*` function — so every
module's migrations are found regardless of which directory they live in,
with zero maintenance burden here as new modules are added.

Deliberately does not use `alembic.config.CommandLine` (Alembic's own
argv-parsing entry point) — that class builds its own `Config` internally
from the `-c`/`--name` arguments before this script would ever get a
chance to call `configure_alembic_version_locations` on it. Implementing
the small subset of subcommands this project actually uses directly
against `alembic.command` avoids fighting that internal construction order.

Usage (from `backend/`, with the venv active):

    python scripts/db.py revision -m "add compliance mapping tables"
    python scripts/db.py revision -m "add a column" --autogenerate
    python scripts/db.py upgrade head
    python scripts/db.py upgrade +1
    python scripts/db.py downgrade -1
    python scripts/db.py current
    python scripts/db.py history
    python scripts/db.py heads

`revision` without `--autogenerate` creates a blank revision template in
`backend/alembic/versions/` (Alembic's own default `version_locations[0]`
for a bare `revision` call, i.e. the *core* directory) — write your own
migration body in this project's established raw-SQL, `IF NOT EXISTS`
style (see any file under `backend/alembic/versions/` or
`backend/app/modules/compliance/migrations/` for the pattern), then, if
it's a first-party module's own migration rather than a core one,
`git mv` the finished file into that module's own `migrations_dir` before
committing — Alembic does not care which of its configured directories a
revision file lives in, only that its `down_revision` points at the
correct prior head, so moving it after the fact (before you commit, not
after) is safe and has no effect on the chain itself.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
# Mirrors `alembic.ini`'s own `prepend_sys_path = .` (which is why `alembic/
# env.py`'s `import app.models` already works when Alembic itself is
# invoked from `backend/`) — this script isn't invoked through Alembic's
# own bootstrapping, so it has to do the equivalent itself before `app` is
# importable, regardless of the caller's own current working directory.
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
