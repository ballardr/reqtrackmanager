"""Re-encrypts every stored secret under the current APP_SECRET_ENCRYPTION_KEY.

To rotate: set APP_SECRET_ENCRYPTION_KEY to the new value and APP_SECRET_ENCRYPTION_KEY_PREVIOUS to the old one,
restart, run this script once, then remove APP_SECRET_ENCRYPTION_KEY_PREVIOUS. Prints counts per column only.

Run from `backend/`:  python scripts/rotate_secret_key.py
"""

from __future__ import annotations

import sys

from app.database import SessionLocal
from app.services import secret_keys


def main() -> int:
    """Rotates, prints the counts and returns a non-zero status when some value could not be decrypted."""
    db = SessionLocal()
    try:
        done = secret_keys.rotate(db)
        unreadable = secret_keys.unreadable_counts(db)
    finally:
        db.close()
    for column, count in done.items():
        print(f"{column}: {count} re-encrypted")
    for column, count in unreadable.items():
        print(f"{column}: {count} could not be decrypted with any configured key")
    return 1 if unreadable else 0


if __name__ == "__main__":
    sys.exit(main())
