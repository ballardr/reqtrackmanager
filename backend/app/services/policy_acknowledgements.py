"""
Module: services.policy_acknowledgements

Acceptance of policies that require it: who must accept, recording an acceptance, the administrators' status view and
export, reminders, and the block on changing records until a required policy is accepted.

Responsibilities:
- Decide which required, published policies apply to a person (a server policy: every active user; an organisation
  policy: the people who may read it, `org_policies.can_view`) and which of them the person has not yet accepted for the
  current version.
- Record an acceptance per person and version with a hash of the accepted text (`PolicyAcknowledgement`).
- List, for an administrator, who has and has not accepted the current version, as rows and as a CSV.
- Notify people with an unaccepted policy, once when a required version is published or the requirement is switched
  on, and again on request.
- Refuse requests that change data from a person with an unaccepted policy (`enforce_accepted`), leaving reading,
  searching, the policies themselves, account sign-in and sign-out, and the administrators' policy routes open.

Design decisions:
- Blocking is narrow on purpose: a published mistake must not become an outage. Only a request that changes data is
  refused (403 `policy_acknowledgement_required`); the policy text stays readable and the person can sign out. A
  requirement is a live setting, so an administrator switches it off at once, without publishing.
- When no policy requires acceptance (the normal case) the check is one indexed existence query.
- A group is never asked as a unit: acceptance is personal. A requirement reaches the people of the policy's audience,
  with effective group membership, exactly as reading does.
- The record holds the person, policy, version, text hash and UTC time only, and states no more than a click by an
  account. It is personal data (Confidential) and is not carried in any bundle.
- Audit events and notifications carry counts and keys, never the policy text.

External dependencies: `services.policies`, `services.org_policies`, `services.notifications`, `services.csv_safety`.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.notification import NotificationType
from app.models.organization import Organization, UserOrgRole
from app.models.policy import PolicyAcknowledgement, PolicyDocument, PolicyDocumentVersion, PolicyState
from app.models.user import User
from app.services import org_policies, policies
from app.services.audit import log_event
from app.services.csv_safety import csv_safe
from app.services.notifications import notify

#: Stable code returned with the refusal, so the interface can send the person to the policy.
BLOCK_CODE = "policy_acknowledgement_required"
#: Most people the status view lists in one response (the export carries every row).
STATUS_LIMIT = 2_000

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
#: Paths that stay open to a person with an unaccepted policy: sign-in and sign-out, the policies and the way to
#: accept them, the administrators' policy routes (so a requirement can be switched off), and reads sent as POST.
_OPEN_PREFIXES = ("/api/v1/auth/", "/api/v1/policies/", "/api/v1/system/policies", "/api/v1/search", "/api/v1/notifications")
_OPEN_PATTERN = re.compile(r"^/api/v1/orgs/[^/]+/policies(/|$)|/files/search$")


@dataclass
class PendingPolicy:
    """A required, published policy that applies to a person, with the version to accept.

    Attributes:
        row: The policy.
        version: Its current published version.
        organization: The owning organisation, or None for a server policy.
        accepted: Whether the person has accepted `version`.
    """

    row: PolicyDocument
    version: PolicyDocumentVersion
    organization: Organization | None
    accepted: bool


def content_hash(version: PolicyDocumentVersion) -> str:
    """SHA-256 of a version's title and body, so an acceptance names the exact text."""
    canonical = json.dumps({"title": version.title, "body": version.body}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def any_required(db: Session) -> bool:
    """Whether any published policy requires acceptance (one indexed existence query)."""
    return bool(db.scalar(select(exists().where(
        PolicyDocument.requires_acknowledgement.is_(True), PolicyDocument.state == PolicyState.PUBLISHED,
    ))))


def applicable(db: Session, user: User) -> list[PendingPolicy]:
    """Every required, published policy that applies to `user`, accepted or not, by organisation then title."""
    org_ids = list(db.scalars(select(UserOrgRole.organization_id).where(UserOrgRole.user_id == user.id).distinct()))
    orgs = {}
    if org_ids:
        orgs = {o.id: o for o in db.scalars(select(Organization).where(Organization.id.in_(org_ids), Organization.is_active.is_(True)))}
    rows = list(db.scalars(select(PolicyDocument).where(
        PolicyDocument.state == PolicyState.PUBLISHED, PolicyDocument.requires_acknowledgement.is_(True),
        (PolicyDocument.organization_id.is_(None)) | (PolicyDocument.organization_id.in_(list(orgs))),
    )))
    if not rows:
        return []
    current = policies.current_versions(db, rows)
    audiences = org_policies.audience_of(db, [r.id for r in rows if r.organization_id is not None])
    accepted = {
        (a.policy_id, a.version)
        for a in db.scalars(select(PolicyAcknowledgement).where(
            PolicyAcknowledgement.user_id == user.id, PolicyAcknowledgement.policy_id.in_([r.id for r in rows]),
        ))
    }
    out = []
    for row in rows:
        version = current.get(row.id)
        if version is None:
            continue
        if row.organization_id is not None and not org_policies.can_view(db, user, row.organization_id, audiences[row.id]):
            continue
        out.append(PendingPolicy(row, version, orgs.get(row.organization_id) if row.organization_id else None, (row.id, version.version) in accepted))
    return sorted(out, key=lambda p: ((p.organization.name.lower() if p.organization else ""), p.version.title.lower()))


def pending(db: Session, user: User) -> list[PendingPolicy]:
    """The required policies `user` has not yet accepted at their current version."""
    return [p for p in applicable(db, user) if not p.accepted]


def acknowledge(db: Session, user: User, policy_id: uuid.UUID, version: int) -> PolicyAcknowledgement:
    """Records that `user` accepted `version` of a policy; audited, not committed. Accepting twice is not an error.

    Raises:
        HTTPException: 404 when the policy is not a required, published policy that applies to the person; 409 when
            `version` is no longer the current version (the text changed while it was open).
    """
    item = next((p for p in applicable(db, user) if p.row.id == policy_id), None)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Policy not found.")
    if item.version.version != version:
        raise HTTPException(status.HTTP_409_CONFLICT, "The policy has changed. Read the current version before accepting it.")
    existing = db.scalars(select(PolicyAcknowledgement).where(
        PolicyAcknowledgement.policy_id == policy_id, PolicyAcknowledgement.version == version, PolicyAcknowledgement.user_id == user.id,
    )).first()
    if existing is not None:
        return existing
    record = PolicyAcknowledgement(
        policy_id=policy_id, version=version, user_id=user.id, content_hash=content_hash(item.version), acknowledged_at=datetime.now(UTC),
    )
    try:
        with db.begin_nested():
            db.add(record)
    except IntegrityError:
        # Two requests accepting at once: the unique constraint lets one through; the other is the same fact.
        return db.scalars(select(PolicyAcknowledgement).where(
            PolicyAcknowledgement.policy_id == policy_id, PolicyAcknowledgement.version == version, PolicyAcknowledgement.user_id == user.id,
        )).one()
    log_event(
        db, entity_type="policy", entity_id=policy_id, action="acknowledged", actor_id=user.id,
        organization_id=item.row.organization_id, detail={"key": item.row.key, "version": version},
    )
    return record


# --- the block ---------------------------------------------------------------------------------------


def is_open_request(method: str, path: str) -> bool:
    """Whether a request stays allowed while a policy is unaccepted (reads, and the paths listed above)."""
    return method.upper() in _SAFE_METHODS or path.startswith(_OPEN_PREFIXES) or _OPEN_PATTERN.search(path) is not None


def enforce_accepted(db: Session, user: User, method: str, path: str) -> None:
    """Refuses a request that changes data while `user` has an unaccepted required policy.

    Raises:
        HTTPException: 403 with `BLOCK_CODE` in the detail.
    """
    if is_open_request(method, path) or not any_required(db):
        return
    waiting = pending(db, user)
    if waiting:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "code": BLOCK_CODE,
                "message": "Accept the policies that require your acceptance before creating or changing records.",
                "policy_ids": [str(p.row.id) for p in waiting],
            },
        )


# --- administrators ----------------------------------------------------------------------------------


@dataclass
class StatusRow:
    """One person in a policy's status view.

    Attributes:
        user: The person.
        accepted_version: The latest version the person accepted, or None.
        accepted_at: When (UTC), or None.
        current: Whether `accepted_version` is the policy's current version.
    """

    user: User
    accepted_version: int | None
    accepted_at: datetime | None
    current: bool


def required_people(db: Session, row: PolicyDocument) -> list[User]:
    """The active people a policy applies to: everyone for a server policy, its readers for an organisation policy."""
    if row.organization_id is None:
        people = list(db.scalars(select(User).where(User.is_active.is_(True), User.is_archived.is_(False))))
    else:
        audience = org_policies.audience_of(db, [row.id])[row.id]
        members = db.scalars(
            select(User).join(UserOrgRole, UserOrgRole.user_id == User.id).where(
                UserOrgRole.organization_id == row.organization_id, User.is_active.is_(True), User.is_archived.is_(False),
            ).distinct()
        )
        people = [u for u in members if org_policies.can_view(db, u, row.organization_id, audience)]
    return sorted(people, key=lambda u: (u.display_name or u.email).lower())


def status_rows(db: Session, row: PolicyDocument) -> list[StatusRow]:
    """Each person the policy applies to with their latest acceptance; those yet to accept the current version first."""
    people = required_people(db, row)
    latest: dict[uuid.UUID, PolicyAcknowledgement] = {}
    for a in db.scalars(select(PolicyAcknowledgement).where(PolicyAcknowledgement.policy_id == row.id).order_by(PolicyAcknowledgement.version)):
        latest[a.user_id] = a
    out = [
        StatusRow(u, latest[u.id].version if u.id in latest else None, latest[u.id].acknowledged_at if u.id in latest else None,
                  u.id in latest and latest[u.id].version == row.current_version)
        for u in people
    ]
    return sorted(out, key=lambda r: (r.current, (r.user.display_name or r.user.email).lower()))


def status_csv(rows: list[StatusRow], current_version: int) -> str:
    """The status rows as a spreadsheet-safe CSV: person, email, status, accepted version and time (UTC)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Name", "Email", "Status", "Accepted version", "Accepted at (UTC)", "Current version"])
    for r in rows:
        state = "Accepted" if r.current else ("Accepted an earlier version" if r.accepted_version else "Not accepted")
        writer.writerow([
            csv_safe(r.user.display_name or ""), csv_safe(r.user.email), state, r.accepted_version or "",
            r.accepted_at.astimezone(UTC).isoformat() if r.accepted_at else "", current_version,
        ])
    return buffer.getvalue()


def notify_unaccepted(db: Session, row: PolicyDocument, actor: User | None, *, include_actor: bool = False) -> int:
    """Tells the people who have not accepted the current version; audited with a count, not committed.

    Returns the number of people notified. The person who triggered it is told only with `include_actor`.
    """
    if row.state != PolicyState.PUBLISHED or not row.requires_acknowledgement:
        return 0
    version = policies.current_versions(db, [row]).get(row.id)
    if version is None:
        return 0
    done = {
        a.user_id for a in db.scalars(select(PolicyAcknowledgement).where(
            PolicyAcknowledgement.policy_id == row.id, PolicyAcknowledgement.version == version.version,
        ))
    }
    count = 0
    for person in required_people(db, row):
        if person.id in done or (not include_actor and actor is not None and person.id == actor.id):
            continue
        sent = notify(
            db, person, notification_type=NotificationType.POLICY_ACKNOWLEDGEMENT_REQUIRED,
            title=f"Policy needs your acceptance: {version.title}", body=version.change_note,
            entity_type="policy", entity_id=str(row.id), actor_id=actor.id if actor else None,
        )
        count += 1 if sent is not None else 0
    log_event(
        db, entity_type="policy", entity_id=row.id, action="acknowledgement_requested", actor_id=actor.id if actor else None,
        organization_id=row.organization_id, detail={"key": row.key, "version": version.version, "recipient_count": count},
    )
    return count


def set_requirement(db: Session, row: PolicyDocument, required: bool, actor: User) -> bool:
    """Switches the requirement on or off; audited, not committed. Returns whether it changed."""
    if row.requires_acknowledgement == required:
        return False
    row.requires_acknowledgement = required
    db.flush()
    log_event(
        db, entity_type="policy", entity_id=row.id, action="acknowledgement_requirement_changed", actor_id=actor.id,
        organization_id=row.organization_id, detail={"key": row.key, "requires_acknowledgement": required},
    )
    return True
