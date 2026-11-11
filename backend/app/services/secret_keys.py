"""
Module: services.secret_keys

Checks and rotation for the application-layer key that encrypts stored secrets (a person's second-factor secret,
an organisation's single sign-on client secret and SMTP password).

Responsibilities:
- `unreadable_counts`: how many stored values of each encrypted column cannot be decrypted with the configured
  keys, run at start-up so a wrong or lost `APP_SECRET_ENCRYPTION_KEY` is a logged error at once rather than
  locked-out users and a broken sign-in later.
- `rotate`: re-encrypts every stored value under the current key (the previous keys are then no longer needed).

Design decisions:
- Column names are a fixed list here, not discovered: the three columns are the product's secrets, and a new one
  must be added deliberately (and to the disaster-recovery verification that lists the same columns).
- Only counts and column names are returned or logged, never a value.

External dependencies: PostgreSQL (raw reads of the stored ciphertext), `models.encrypted_type`.
"""

from __future__ import annotations

import logging

from cryptography.fernet import InvalidToken
from sqlalchemy import column, select, table, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import ColumnClause

from app.models.encrypted_type import decrypts_with_current_key, re_encrypt

logger = logging.getLogger(__name__)

#: (table, column) of every `EncryptedString` column.
ENCRYPTED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("users", "totp_secret"),
    ("organizations", "oidc_client_secret"),
    ("organizations", "smtp_password"),
)


def unreadable_counts(db: Session) -> dict[str, int]:
    """Per column, how many stored values the configured keys cannot decrypt (columns with none are omitted)."""
    unreadable: dict[str, int] = {}
    for table_name, column_name in ENCRYPTED_COLUMNS:
        secret: ColumnClause = column(column_name)
        rows = db.execute(select(secret).select_from(table(table_name)).where(secret.is_not(None))).scalars().all()
        bad = sum(1 for value in rows if not decrypts_with_current_key(value))
        if bad:
            unreadable[f"{table_name}.{column_name}"] = bad
    return unreadable


def warn_if_unreadable(db: Session) -> dict[str, int]:
    """Logs an error naming each column with undecryptable values (counts only) and returns the counts."""
    unreadable = unreadable_counts(db)
    for name, count in unreadable.items():
        logger.error(
            "%d stored value(s) in %s cannot be decrypted with APP_SECRET_ENCRYPTION_KEY or "
            "APP_SECRET_ENCRYPTION_KEY_PREVIOUS: the key was changed without being kept as a previous key.",
            count, name,
        )
    return unreadable


def rotate(db: Session) -> dict[str, int]:
    """Re-encrypts every stored secret under the current key and commits.

    Returns:
        Per column, how many values were re-encrypted. A value no configured key can decrypt is left as it is
        and counted by `unreadable_counts`, so a half-finished rotation cannot destroy it.
    """
    done: dict[str, int] = {}
    for table_name, column_name in ENCRYPTED_COLUMNS:
        secret: ColumnClause = column(column_name)
        row_key: ColumnClause = column("id")
        target = table(table_name, row_key, secret)
        rows = db.execute(select(row_key, secret).select_from(target).where(secret.is_not(None))).all()
        count = 0
        for row_id, value in rows:
            try:
                fresh = re_encrypt(value)
            except InvalidToken:
                continue
            db.execute(update(target).where(row_key == row_id).values({column_name: fresh}))
            count += 1
        done[f"{table_name}.{column_name}"] = count
    db.commit()
    return done
