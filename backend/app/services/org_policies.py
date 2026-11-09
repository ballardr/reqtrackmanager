"""
Module: services.org_policies

An organisation's own policies (an access policy, a confidentiality agreement, ...): who may read each, whether
links are allowed in them, the notification on publication, what a signed-in member sees, and the organisation bundle.

Responsibilities:
- Hold the audience of a policy (every member, or named users and organisation groups) and the one visibility rule
  (`can_view`) used by the reader list and the reader read.
- List the published policies of every organisation a person belongs to, with their current versions.
- Decide whether links are allowed (`Organization.allow_policy_links`) and re-check a working copy against it at publication.
- Notify the audience when a policy is published, only when the publisher chose to.
- Export and import the organisation's policies and their versions as an `org.json` section.

Design decisions:
- Writing is `services.policies` with the owner passed in (one implementation); this module adds only what is
  organisation-specific.
- A policy the caller may not read is a 404, never a 403, so its existence is not revealed.
- An organisation administrator always reads every policy of their organisation. A person with no role in the
  organisation never does, and a policy of a disabled organisation is not listed.
- An audience member must be a member or an organisation group of this organisation (`principals.validate_principal`
  with no project, so a project group is refused). The reference is mandatory
  (`principals.CORE_PRINCIPAL_REFERENCES`): deleting a group that restricts a policy needs a replacement, so removing a
  group never widens who may read it.
- Audit events and notifications carry counts and keys, never the policy text.
- A bundle carries each policy's working copy, audience (by email or group name) and published versions, but always
  imports as a draft, so an import never publishes text in the new organisation's name unreviewed. An audience member
  that cannot be matched stands as the importing user, so an import never widens a restricted policy.

External dependencies: `services.policies`, `services.policy_body`, `services.principals`, `services.notifications`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.enums import OrgRole, PrincipalType
from app.models.notification import NotificationType
from app.models.organization import Organization, UserOrgRole
from app.models.policy import PolicyAudience, PolicyDocument, PolicyDocumentVersion, PolicyState
from app.models.user import User
from app.schemas.principal import PrincipalRef
from app.services import policies
from app.services.audit import log_event
from app.services.bundle_common import BundleImportWarnings
from app.services.notifications import notify
from app.services.policy_body import plain_text, validate_body
from app.services.principals import is_principal_member, principal_from_bundle, principal_to_bundle, validate_principal
from app.services.rbac import get_effective_org_roles

BUNDLE_KEY = "policies"
#: Most people or groups one policy may be limited to.
MAX_AUDIENCE = 50
#: Titles the add dialog suggests; they only fill the title field.
STARTER_TITLES = ("Access policy", "Confidentiality agreement", "Acceptable use policy", "Code of conduct")


@dataclass
class ReaderPolicy:
    """A published policy as a member's Policies page lists it.

    Attributes:
        organization: The owning organisation.
        row: The policy.
        version: Its current published version.
    """

    organization: Organization
    row: PolicyDocument
    version: PolicyDocumentVersion


# --- links setting ----------------------------------------------------------------------------------


def links_allowed(db: Session, organization_id: uuid.UUID) -> bool:
    """Whether the organisation's policies may contain links."""
    return bool(db.scalar(select(Organization.allow_policy_links).where(Organization.id == organization_id)))


def set_links_allowed(db: Session, organization_id: uuid.UUID, allowed: bool, actor: User) -> bool:
    """Sets whether the organisation's policies may contain links; audited, not committed.

    Turning it off does not change a stored text: a working copy with a link fails the next save and publication until
    the link is removed, and an already published version stays as it was published.
    """
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found.")
    if org.allow_policy_links != allowed:
        org.allow_policy_links = allowed
        db.flush()
        log_event(
            db, entity_type="organization", entity_id=organization_id, action="policy_links_changed", actor_id=actor.id,
            organization_id=organization_id, detail={"allow_policy_links": allowed},
        )
    return allowed


# --- audience ---------------------------------------------------------------------------------------


def audience_of(db: Session, policy_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[PrincipalRef]]:
    """The audience of each policy, read once (an empty list: every member)."""
    found: dict[uuid.UUID, list[PrincipalRef]] = {policy_id: [] for policy_id in policy_ids}
    if policy_ids:
        for row in db.scalars(select(PolicyAudience).where(PolicyAudience.policy_id.in_(policy_ids))):
            found[row.policy_id].append(PrincipalRef(type=PrincipalType(row.audience_type), id=row.audience_id))
    return found


def set_audience(db: Session, row: PolicyDocument, audience: list[PrincipalRef], actor: User) -> None:
    """Replaces who the policy is limited to; audited with the count, not committed.

    Raises:
        HTTPException: 422 for a server policy, too many or repeated entries; 400 for a user outside the organisation
            or a group of another one (and for a project group).
    """
    if row.organization_id is None:
        if audience:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A server policy is for everyone and has no audience.")
        return
    if len(audience) > MAX_AUDIENCE:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"A policy may be limited to at most {MAX_AUDIENCE} people or groups.")
    if len({(a.type, a.id) for a in audience}) != len(audience):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A person or group may be listed once.")
    for entry in audience:
        validate_principal(db, entry, organization_id=row.organization_id, project_id=None, field="audience")
    before = audience_of(db, [row.id])[row.id]
    if {(a.type, a.id) for a in before} == {(a.type, a.id) for a in audience}:
        return
    db.execute(delete(PolicyAudience).where(PolicyAudience.policy_id == row.id))
    for entry in audience:
        db.add(PolicyAudience(policy_id=row.id, audience_type=entry.type.value, audience_id=entry.id))
    db.flush()
    log_event(
        db, entity_type="policy", entity_id=row.id, action="audience_changed", actor_id=actor.id,
        organization_id=row.organization_id, detail={"key": row.key, "audience_count": len(audience)},
    )


def can_view(db: Session, user: User, organization_id: uuid.UUID, audience: list[PrincipalRef]) -> bool:
    """Whether `user` may read a policy limited to `audience`.

    An organisation administrator always may; another member may when the policy has no audience or they are in it (a
    user directly, a group by effective membership); a person with no role in the organisation never may.
    """
    roles = get_effective_org_roles(db, user.id, organization_id)
    if OrgRole.ORG_ADMIN in roles:
        return True
    if not roles:
        return False
    return not audience or any(is_principal_member(db, entry, user.id) for entry in audience)


# --- readers ----------------------------------------------------------------------------------------


def published_for(db: Session, user: User) -> list[ReaderPolicy]:
    """The published policies `user` may read, across their organisations, by organisation name then slot order."""
    org_ids = list(db.scalars(select(UserOrgRole.organization_id).where(UserOrgRole.user_id == user.id).distinct()))
    if not org_ids:
        return []
    orgs = {o.id: o for o in db.scalars(select(Organization).where(Organization.id.in_(org_ids), Organization.is_active.is_(True)))}
    rows = [
        r for r in db.scalars(select(PolicyDocument).where(
            PolicyDocument.organization_id.in_(list(orgs)), PolicyDocument.state == PolicyState.PUBLISHED,
        ))
    ]
    current = policies.current_versions(db, rows)
    audiences = audience_of(db, [r.id for r in rows])
    out = [
        ReaderPolicy(orgs[r.organization_id], r, current[r.id])
        for r in rows
        if r.organization_id is not None and r.id in current and can_view(db, user, r.organization_id, audiences[r.id])
    ]
    return sorted(out, key=lambda p: (p.organization.name.lower(), p.version.title.lower()))


def reader_policy(db: Session, user: User, policy_id: uuid.UUID) -> ReaderPolicy:
    """One published organisation policy as `user` may read it.

    Raises:
        HTTPException: 404 when it does not exist, is not published, belongs to no organisation of the caller or is
            limited to an audience the caller is not in (the same answer for each).
    """
    for item in published_for(db, user):
        if item.row.id == policy_id:
            return item
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Policy not found.")


# --- publication ------------------------------------------------------------------------------------


def check_publishable(db: Session, row: PolicyDocument) -> None:
    """Re-checks the working copy against the organisation's link setting before it is published.

    Raises:
        HTTPException: 422 when the text has a link and the organisation no longer allows links.
    """
    if row.organization_id is not None:
        validate_body(row.body, allow_links=links_allowed(db, row.organization_id))


def notify_audience(db: Session, row: PolicyDocument, version: PolicyDocumentVersion, actor: User) -> int:
    """Tells the people who may read a newly published policy; audited with a count, not committed.

    The publisher is not notified of their own action. Returns the number of people notified.
    """
    if row.organization_id is None:
        return 0
    audience = audience_of(db, [row.id])[row.id]
    members = db.scalars(
        select(User).join(UserOrgRole, UserOrgRole.user_id == User.id).where(
            UserOrgRole.organization_id == row.organization_id, User.is_active.is_(True), User.is_archived.is_(False),
        ).distinct()
    )
    count = 0
    for person in members:
        if person.id == actor.id or not can_view(db, person, row.organization_id, audience):
            continue
        sent = notify(
            db, person, notification_type=NotificationType.POLICY_PUBLISHED, title=f"Policy published: {version.title}",
            body=version.change_note, entity_type="policy", entity_id=str(row.id), actor_id=actor.id,
        )
        count += 1 if sent is not None else 0
    log_event(
        db, entity_type="policy", entity_id=row.id, action="notified", actor_id=actor.id, organization_id=row.organization_id,
        detail={"key": row.key, "version": version.version, "recipient_count": count},
    )
    return count


# --- organisation bundle ----------------------------------------------------------------------------


def export_org(db: Session, organization_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
    """The organisation's policies as an `org.json` section.

    Each entry carries the working copy, the audience (by email or group name) and every published version. Authors and
    publishers are not carried (kept in the source deployment's audit log).
    """
    rows = policies.list_scope(db, organization_id)
    audiences = audience_of(db, [r.id for r in rows])
    entries = []
    for row in rows:
        entries.append({
            "title": row.title, "body": row.body,
            "effective_from": row.effective_from.isoformat() if row.effective_from else None,
            "audience": [b for a in audiences[row.id] if (b := principal_to_bundle(db, a.type.value, a.id)) is not None],
            "versions": [
                {
                    "version": v.version, "title": v.title, "body": v.body,
                    "effective_from": v.effective_from.isoformat() if v.effective_from else None,
                    "published_at": v.published_at.isoformat(), "change_note": v.change_note,
                }
                for v in reversed(policies.versions(db, row))
            ],
        })
    return {BUNDLE_KEY: entries}


def _date(value: object) -> date | None:
    """A plain `YYYY-MM-DD` date, or None when absent or not one."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _instant(value: object) -> datetime:
    """An ISO 8601 instant with an offset (UTC assumed when it has none), or now when it cannot be read."""
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def import_org(
    db: Session, organization_id: uuid.UUID, data: dict[str, Any], actor: User, warnings: BundleImportWarnings,
) -> None:
    """Adds the bundle's policies to an organisation, always as drafts.

    A policy whose title the organisation already has is kept as it is (an import never overwrites). The published
    versions arrive as history, and the policy stays unpublished until someone publishes it again. A text that is not valid
    here (an unsafe link, or a link where the organisation allows none) is skipped with a warning, version by version.
    """
    raw = data.get(BUNDLE_KEY)
    allow_links = links_allowed(db, organization_id)
    held = {r.title.lower() for r in policies.list_scope(db, organization_id)}
    count = len(held)
    cache: dict[Any, Any] = {}
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("title"), str):
            warnings.add("A policy in the bundle was not imported because it is not valid here.")
            continue
        try:
            title = policies.clean_title(entry["title"])
            body = validate_body(entry.get("body") or {}, allow_links=allow_links)
        except HTTPException:
            warnings.add("A policy in the bundle was not imported because its text is not valid here.")
            continue
        if title.lower() in held:
            continue
        if count >= policies.MAX_PER_SCOPE:
            warnings.add(f"Policies beyond the limit of {policies.MAX_PER_SCOPE} were not imported.")
            break
        row = PolicyDocument(
            organization_id=organization_id, key=None, title=title, body=body, state=PolicyState.DRAFT,
            effective_from=_date(entry.get("effective_from")), current_version=0, created_by=actor.id,
        )
        db.add(row)
        db.flush()
        top = 0
        for item in entry.get("versions") or []:
            try:
                number = int(item["version"])
                version_body = validate_body(item.get("body") or {}, allow_links=allow_links)
                if number < 1 or not plain_text(version_body):
                    raise ValueError("empty")
                db.add(PolicyDocumentVersion(
                    policy_id=row.id, version=number, title=policies.clean_title(str(item.get("title") or title)), body=version_body,
                    effective_from=_date(item.get("effective_from")), published_at=_instant(item.get("published_at")),
                    published_by=None, change_note=str(item.get("change_note") or "")[: policies.MAX_NOTE_LENGTH],
                ))
                top = max(top, number)
            except (KeyError, TypeError, ValueError, HTTPException):
                warnings.add(f"A published version of policy '{title}' was not imported because it is not valid here.")
        row.current_version = top
        members: list[PrincipalRef] = []
        for bundled in entry.get("audience") or []:
            ref, warning = principal_from_bundle(
                db, bundled, organization_id=organization_id, project_id=None, fallback_user_id=actor.id, user_cache=cache,
            )
            if warning:
                warnings.add(f"Policy '{title}': {warning}")
            if ref is not None and all((m.type, m.id) != (ref.type, ref.id) for m in members):
                members.append(ref)
        for member in members[:MAX_AUDIENCE]:
            db.add(PolicyAudience(policy_id=row.id, audience_type=member.type.value, audience_id=member.id))
        held.add(title.lower())
        count += 1
    db.flush()
