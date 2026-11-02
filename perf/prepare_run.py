"""
Module: perf.prepare_run

Sets the password of every generated person and of the server administrator to this run's throwaway one. Runs
inside the performance stack's backend container (`PERF_STACK=1`, this directory mounted at `/perf`).

Responsibilities:
- After a dataset snapshot is restored (its password hashes belong to the run that made it), set one bcrypt hash
  on the server administrator and on every `@perf.example.com` account.

Design decisions:
- One hash for all accounts (bcrypt is deliberately slow), applied with a single UPDATE.
- Increments `token_version`, so no token from the snapshot's run can still work.
- Refuses to run outside the performance stack, exactly as the generator does.

Dependencies: the backend image (`app.*`).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.environ.get("PERF_APP_DIR", "/app"))


def main() -> int:
    """Updates the passwords; returns the process exit status."""
    from sqlalchemy import update

    from app.database import SessionLocal
    from app.models.user import User
    from app.security import hash_password
    from app.services.perf_dataset.build import RefusedToRun, require_perf_stack
    from app.services.perf_dataset.skeleton import EMAIL_DOMAIN

    try:
        require_perf_stack()
    except RefusedToRun as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    hashed = hash_password(os.environ["PERF_USER_PASSWORD"])
    admin_hashed = hash_password(os.environ["SERVER_ADMIN_PASSWORD"])
    db = SessionLocal()
    try:
        people = db.execute(
            update(User).where(User.email.like(f"%@{EMAIL_DOMAIN}")).values(password_hash=hashed, token_version=User.token_version + 1)
        ).rowcount
        admins = db.execute(
            update(User).where(User.email == os.environ["SERVER_ADMIN_EMAIL"].lower()).values(password_hash=admin_hashed, token_version=User.token_version + 1)
        ).rowcount
        db.commit()
    finally:
        db.close()
    print(f"passwords set for {people} generated accounts and {admins} administrator")
    return 0


if __name__ == "__main__":
    sys.exit(main())
