"""
Module: services.imported_people

Imported people: inert stand-ins for the people a bundle names who are not members of the organisation importing it.

Responsibilities:
- Create or reuse a stand-in `User` row per organisation and person (`stand_in_for`), keyed by an HMAC of the
  normalised email so the address itself is never stored and a later import into the same organisation reuses the row.
- Read the people a bundle names (`bundle_emails`) and write the display names that travel with it (`people_section`).
- Classify each person for the import preview (`classify_people`) and hold the importer's per-person choices
  (`PeopleChoices`).
- List and remove unused stand-ins (`unused_stand_ins`, `anonymise`).

Design decisions:
- A stand-in is a user row because about 25 authorship and owner columns are non-null foreign keys to `users`. It is
  always inactive and archived with no password, an `imported` backend and a synthetic non-routable address, so the
  checks that already refuse a deactivated account (sign-in, role and group grants, invitations, notification
  delivery, pickers) refuse it without a per-route rule; `User.imported_organization_id` marks it for display and the
  People page. It holds no role, so it is absent from every member list and count.
- The bundle's email is not stored on the stand-in. Whether it is kept in the replayed history's detail is the
  importer's choice at import time (`PeopleChoices.keep_original_email`).
- A stand-in is never merged into a real account later; re-pointing authorship would rewrite history.

External dependencies: `app.config.settings` (HMAC key), `models.user`, `models.organization`.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base
from app.models.enums import PrincipalType
from app.models.organization import Organization, UserOrgRole
from app.models.user import User
from app.services.principals import all_principal_references, reference_columns

#: Value of `User.auth_backend` on a stand-in; no backend answers to it, so no sign-in path matches.
IMPORTED_BACKEND = "imported"
#: Domain of a stand-in's synthetic address: reserved for documentation (RFC 2606) with no mail exchanger, so nothing is
#: delivered. `.invalid` would be the natural choice, but the email validators the API schemas use reject it.
IMPORTED_EMAIL_DOMAIN = "imported.example.com"
#: Display name used when a bundle gives none.
FALLBACK_NAME = "Imported person"
#: Importer choice meaning "the importer themself" and "a new stand-in".
CHOICE_ME = "me"
CHOICE_STAND_IN = "stand_in"

_MAX_NAME = 200
_MAX_PEOPLE = 5000
_MAX_NODES = 5_000_000
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_EMAIL_KEY = re.compile(r"(^|_)email$")


def normalise_email(value: str) -> str:
    """The address as compared everywhere: trimmed and lower-case."""
    return value.strip().lower()


def clean_name(value: Any, email: str) -> str:
    """A display name safe to store: control characters removed, bounded, and derived from the address when absent.

    Args:
        value: The bundle's recorded name (any type; a non-string is ignored).
        email: The person's normalised address, used only to derive a readable name when `value` is empty.

    Returns:
        A non-empty name of at most 200 characters.
    """
    name = _CONTROL.sub("", value).strip() if isinstance(value, str) else ""
    if not name:
        local = email.split("@", 1)[0]
        name = " ".join(part.capitalize() for part in re.split(r"[._\-+\s]+", local) if part)
    return (name or FALLBACK_NAME)[:_MAX_NAME]


def person_key(organization_id: uuid.UUID, email: str) -> str:
    """Keyed hash of a person's address within one organisation (hex, 64 characters).

    The key is the application's secret encryption key, so the hash cannot be recomputed from an address without it and
    the same address hashes differently in every organisation. Rotating that key only means a later import creates a
    new stand-in instead of reusing the old one.
    """
    message = f"{organization_id}:{normalise_email(email)}".encode()
    return hmac.new(get_settings().app_secret_encryption_key.encode(), message, hashlib.sha256).hexdigest()


def is_imported_person(user: User | None) -> bool:
    """Whether the account is an imported person (a stand-in)."""
    return user is not None and user.imported_organization_id is not None


def assert_not_imported_person(user: User) -> None:
    """Raises 409 when the account is an imported person, which can never be reactivated, banned or signed in as.

    Raises:
        HTTPException: 409 for an imported person.
    """
    if is_imported_person(user):
        raise HTTPException(status.HTTP_409_CONFLICT, "An imported person is a record of someone named in an import and cannot be changed this way.")


def stand_in_for(db: Session, organization_id: uuid.UUID, email: str, display_name: str | None = None) -> User:
    """The organisation's stand-in for an address, created on first use.

    Args:
        db: Active session; a new row is flushed, not committed.
        organization_id: The organisation importing the bundle; a stand-in belongs to exactly one.
        email: The bundle's address for the person (used only to derive the key and, if no name is given, a name).
        display_name: The bundle's recorded name for the person.

    Returns:
        The existing stand-in for this key, or a new inactive, archived user with a synthetic address and no password.
    """
    normalised = normalise_email(email)
    key = person_key(organization_id, normalised)
    existing = db.scalar(select(User).where(User.imported_organization_id == organization_id, User.imported_key == key))
    if existing is not None:
        return existing
    user = User(
        email=f"imported-{uuid.uuid4()}@{IMPORTED_EMAIL_DOMAIN}", display_name=clean_name(display_name, normalised),
        password_hash=None, auth_backend=IMPORTED_BACKEND, is_active=False, is_archived=True,
        imported_organization_id=organization_id, imported_key=key, display_name_locked=True,
    )
    db.add(user)
    db.flush()
    return user


def bundle_emails(data: Any) -> set[str]:
    """Every address a bundle's data names, found by shape rather than by module.

    An address is the string value of any key called `email` or ending in `_email` (a bundled principal is
    `{"type": "user", "email": ...}`). Walking the whole structure means a module that adds a `*_email` field is covered
    with no edit here.

    Args:
        data: The parsed bundle JSON (any nesting of dicts and lists).

    Returns:
        The distinct normalised addresses, capped at 5000.
    """
    found: set[str] = set()
    stack: list[Any] = [data]
    seen = 0
    while stack and len(found) < _MAX_PEOPLE:
        node = stack.pop()
        seen += 1
        if seen > _MAX_NODES:
            break
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str) and _EMAIL_KEY.search(key):
                    if normalise_email(value) and "@" in value:
                        found.add(normalise_email(value))
                elif isinstance(value, dict | list):
                    stack.append(value)
        elif isinstance(node, list):
            stack.extend(item for item in node if isinstance(item, dict | list))
    return found


def people_section(db: Session, data: dict[str, Any]) -> list[dict[str, str]]:
    """The `people` entry of a bundle: each named person's address and display name, in one query.

    Args:
        db: Active session (read only).
        data: The bundle's JSON built so far; its addresses are collected with `bundle_emails`.

    Returns:
        `[{"email", "display_name"}]` sorted by address. An address with no account in this deployment is omitted
        (an import derives a name from it). A stand-in's own synthetic address is never exported.
    """
    emails = {e for e in bundle_emails(data) if not e.endswith(f"@{IMPORTED_EMAIL_DOMAIN}")}
    if not emails:
        return []
    rows = db.execute(
        select(func.lower(User.email), User.display_name).where(func.lower(User.email).in_(emails)).order_by(User.email)
    ).all()
    return [{"email": email, "display_name": name} for email, name in rows]


def people_names(data: dict[str, Any]) -> dict[str, str]:
    """`{normalised address: display name}` from a bundle's `people` entry; a malformed entry is skipped."""
    names: dict[str, str] = {}
    entries = data.get("people")
    if not isinstance(entries, list):
        return names
    for entry in entries[:_MAX_PEOPLE]:
        if isinstance(entry, dict) and isinstance(entry.get("email"), str):
            names[normalise_email(entry["email"])] = clean_name(entry.get("display_name"), normalise_email(entry["email"]))
    return names


@dataclass
class PeopleChoices:
    """The importer's decisions about the people in a bundle.

    Attributes:
        mapping: Per normalised address: `"me"` (the importer), `"stand_in"` (a stand-in even where a member matches),
            or the id of an organisation member the person is reassigned to. An address not listed is matched
            automatically by email and otherwise becomes a stand-in.
        keep_original_email: Whether a replayed history entry keeps the original person's address in its detail.
    """

    mapping: dict[str, str] = field(default_factory=dict)
    keep_original_email: bool = False

    @classmethod
    def from_json(cls, raw: Any) -> PeopleChoices:
        """Parses the request's JSON choices; a malformed value yields the defaults (no choices)."""
        if not isinstance(raw, dict):
            return cls()
        mapping_raw = raw.get("mapping")
        mapping = {
            normalise_email(k): v for k, v in (mapping_raw.items() if isinstance(mapping_raw, dict) else [])
            if isinstance(k, str) and isinstance(v, str)
        }
        return cls(mapping=mapping, keep_original_email=raw.get("keep_original_email") is True)


@dataclass
class PersonPreview:
    """One person in the import preview: how they will be resolved and the member they match, if any."""

    email: str
    display_name: str
    resolution: str  # "member", "stand_in", "me" or "reassigned"
    member_id: uuid.UUID | None = None
    member_name: str | None = None


def members_by_email(db: Session, organization_id: uuid.UUID, emails: set[str]) -> dict[str, User]:
    """The organisation's members among these addresses, `{normalised address: user}`, in one query."""
    if not emails:
        return {}
    rows = db.scalars(
        select(User).join(UserOrgRole, UserOrgRole.user_id == User.id)
        .where(func.lower(User.email).in_(emails), UserOrgRole.organization_id == organization_id,
               User.imported_organization_id.is_(None))
    ).all()
    return {normalise_email(u.email): u for u in rows}


def classify_people(
    db: Session, organization_id: uuid.UUID, data: dict[str, Any], choices: PeopleChoices,
) -> list[PersonPreview]:
    """How each person a bundle names would be resolved, for the import preview.

    Args:
        db: Active session (read only).
        organization_id: The organisation importing.
        data: The bundle's parsed JSON.
        choices: The importer's decisions so far.

    Returns:
        One entry per distinct address, sorted by name. A mapping to an id that is not a member of the organisation is
        reported as the automatic resolution, never silently honoured.
    """
    emails = bundle_emails(data)
    names = people_names(data)
    members = members_by_email(db, organization_id, emails)
    chosen_ids = {v for v in choices.mapping.values() if v not in (CHOICE_ME, CHOICE_STAND_IN)}
    reassigned = _members_by_id(db, organization_id, chosen_ids)
    out: list[PersonPreview] = []
    for email in sorted(emails):
        name = names.get(email) or clean_name(None, email)
        choice = choices.mapping.get(email)
        if choice == CHOICE_ME:
            out.append(PersonPreview(email, name, "me"))
        elif choice == CHOICE_STAND_IN:
            out.append(PersonPreview(email, name, "stand_in"))
        elif choice in reassigned:
            target = reassigned[choice]
            out.append(PersonPreview(email, name, "reassigned", target.id, target.display_name))
        elif email in members:
            out.append(PersonPreview(email, name, "member", members[email].id, members[email].display_name))
        else:
            out.append(PersonPreview(email, name, "stand_in"))
    return sorted(out, key=lambda p: (p.display_name.lower(), p.email))


def _members_by_id(db: Session, organization_id: uuid.UUID, ids: set[str]) -> dict[str, User]:
    """Organisation members among string user ids (a malformed id or a non-member is left out)."""
    parsed: dict[uuid.UUID, str] = {}
    for raw in ids:
        try:
            parsed[uuid.UUID(raw)] = raw
        except ValueError:
            continue
    if not parsed:
        return {}
    rows = db.scalars(
        select(User).join(UserOrgRole, UserOrgRole.user_id == User.id)
        .where(User.id.in_(parsed), UserOrgRole.organization_id == organization_id, User.is_active.is_(True),
               User.is_archived.is_(False), User.is_banned.is_(False))
    ).all()
    return {parsed[u.id]: u for u in rows}


def reassignable_member(db: Session, organization_id: uuid.UUID, raw_id: str) -> User | None:
    """The active organisation member a reassignment names, or `None` when it is not one."""
    return _members_by_id(db, organization_id, {raw_id}).get(raw_id)


def unused_stand_ins(db: Session, organization: Organization, *, now: datetime | None = None) -> list[User]:
    """The organisation's stand-ins that are due to be offered for removal.

    Args:
        db: Active session (read only).
        organization: The organisation; its `imported_person_retention_days` decides, and `None` offers nothing.
        now: The comparison instant (UTC); defaults to the current time.

    Returns:
        Stand-ins older than the retention period that no record refers to (see `references`).
    """
    days = organization.imported_person_retention_days
    if days is None:
        return []
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    candidates = db.scalars(
        select(User).where(User.imported_organization_id == organization.id, User.created_at < cutoff)
    ).all()
    return [u for u in candidates if not references(db, u.id)]


def referenced_ids(db: Session, user_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """The users among `user_ids` that anything still refers to.

    Two kinds of reference are read: every foreign key to `users` in the schema metadata, and every declared principal
    field (an owner, assignee or reviewer stores a type and an id with no foreign key). Reading both from registries
    means a table or a module added later is covered with no list to maintain here.

    Args:
        db: Active session (read only).
        user_ids: The users to test.

    Returns:
        The subset that is referenced; one query per referencing column, not per user.
    """
    wanted = set(user_ids)
    found: set[uuid.UUID] = set()
    if not wanted:
        return found
    for table in Base.metadata.sorted_tables:
        if table.name == "users":
            continue
        for column in table.columns:
            if any(fk.column.table.name == "users" and fk.column.name == "id" for fk in column.foreign_keys):
                found.update(db.scalars(select(column).where(column.in_(wanted - found)).distinct()).all())
    for reference in all_principal_references():
        type_column, id_column = reference_columns(reference)
        found.update(
            db.scalars(
                select(id_column).where(type_column == PrincipalType.USER.value, id_column.in_(wanted - found)).distinct()
            ).all()
        )
    return found & wanted


def references(db: Session, user_id: uuid.UUID) -> bool:
    """Whether anything refers to the user (see `referenced_ids`)."""
    return user_id in referenced_ids(db, [user_id])


def anonymise(db: Session, user: User) -> None:
    """Replaces a stand-in's name with "Former person"; its records and history stay.

    Raises:
        ValueError: If the account is not an imported person.
    """
    if not is_imported_person(user):
        raise ValueError("Only an imported person can be anonymised.")
    user.display_name = "Former person"
    db.flush()
