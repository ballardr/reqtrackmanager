"""
Module: routers.policies

Policies (written documents such as a privacy policy):
- `/api/v1/system/policies`: server administrators write, publish and retire server policies.
- `/api/v1/orgs/{id}/policies`: organisation administrators do the same for the organisation's own policies, set who
  may read each, and choose whether links are allowed.
- `GET /api/v1/public/policies` and `/{id}`: public, rate-limited; the published server policies.
- `GET /api/v1/policies/mine` and `/{id}`: signed in; the published policies of the caller's organisations that the
  caller may read.
- `GET /api/v1/policies/mine/pending` and `POST /api/v1/policies/mine/{id}/acknowledge`: the policies the caller must
  accept and the acceptance; administrators also read who has accepted (`/{id}/acknowledgements`, its CSV export and a
  reminder) for the server's policies and their organisation's.

Authorisation: scope is enforced in `services.policies` (a policy of another scope is a 404) and readers' visibility in
`services.org_policies` (a policy the caller may not read is a 404). The public read returns only published content
(never the author, working copy, change note or an unpublished policy).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip, get_current_session_user, get_current_user
from app.models.enums import OrgRole
from app.models.policy import PolicyDocument, PolicyDocumentVersion, PolicyState
from app.models.user import User
from app.schemas.policies import (
    AcknowledgeIn,
    AcknowledgementOut,
    AcknowledgementStatusOut,
    AcknowledgementStatusRowOut,
    MemberPolicyOut,
    MemberPolicySummaryOut,
    OrgPolicyAudienceLookupIn,
    OrgPolicyIn,
    OrgPolicyOut,
    OrgPolicyPublishIn,
    OrgPolicySettingsIn,
    OrgPolicySettingsIO,
    OrgPolicySummaryOut,
    PendingPolicyOut,
    PolicyIn,
    PolicyOut,
    PolicyPublishIn,
    PolicySummaryOut,
    PolicyVersionBodyOut,
    PolicyVersionOut,
    PublicPolicyOut,
    PublicPolicySummaryOut,
    ReminderOut,
)
from app.schemas.principal import PrincipalOut, PrincipalRef
from app.services import org_policies
from app.services import policies as service
from app.services import policy_acknowledgements as acks
from app.services.audit import log_event
from app.services.principals import principal_labels, validate_principal
from app.services.rbac import require_org_role, require_server_admin

system_router = APIRouter(prefix="/api/v1/system/policies", tags=["policies"])
org_router = APIRouter(prefix="/api/v1/orgs/{organization_id}/policies", tags=["policies"])
member_router = APIRouter(prefix="/api/v1/policies/mine", tags=["policies"])
public_router = APIRouter(prefix="/api/v1/public/policies", tags=["policies"])

_org_admin = require_org_role(OrgRole.ORG_ADMIN)


def _summary(row: PolicyDocument, current: PolicyDocumentVersion | None) -> PolicySummaryOut:
    return PolicySummaryOut(
        id=row.id, key=row.key, title=row.title, state=row.state, effective_from=row.effective_from,
        current_version=row.current_version, has_unpublished_changes=service.has_unpublished_changes(row, current),
        updated_at=row.updated_at, requires_acknowledgement=row.requires_acknowledgement,
    )


def _version_out(v: PolicyDocumentVersion) -> PolicyVersionOut:
    return PolicyVersionOut(
        version=v.version, title=v.title, effective_from=v.effective_from, published_at=v.published_at, change_note=v.change_note,
    )


def _out(db: Session, row: PolicyDocument) -> PolicyOut:
    history = service.versions(db, row)
    current = next((v for v in history if v.version == row.current_version), None)
    return PolicyOut(**_summary(row, current).model_dump(), body=row.body, versions=[_version_out(v) for v in history])


def _apply_requirement(db: Session, row: PolicyDocument, body: PolicyIn, actor: User) -> None:
    """Applies `requires_acknowledgement` when the request sends it; asks for acceptance when it is switched on for a published policy."""
    if body.requires_acknowledgement is not None and acks.set_requirement(db, row, body.requires_acknowledgement, actor):
        acks.notify_unaccepted(db, row, actor)


def _status_out(db: Session, row: PolicyDocument) -> AcknowledgementStatusOut:
    rows = acks.status_rows(db, row)
    return AcknowledgementStatusOut(
        policy_id=row.id, title=row.title, version=row.current_version, requires_acknowledgement=row.requires_acknowledgement,
        required=len(rows), accepted=sum(1 for r in rows if r.current), truncated=len(rows) > acks.STATUS_LIMIT,
        people=[
            AcknowledgementStatusRowOut(
                user_id=r.user.id, display_name=r.user.display_name, email=r.user.email, accepted_version=r.accepted_version,
                accepted_at=r.accepted_at, current=r.current,
            )
            for r in rows[: acks.STATUS_LIMIT]
        ],
    )


def _status_csv(db: Session, row: PolicyDocument, actor: User) -> Response:
    rows = acks.status_rows(db, row)
    log_event(
        db, entity_type="policy", entity_id=row.id, action="acknowledgements_exported", actor_id=actor.id,
        organization_id=row.organization_id, detail={"key": row.key, "version": row.current_version, "row_count": len(rows)},
    )
    db.commit()
    return Response(
        content=acks.status_csv(rows, row.current_version), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="policy-acceptances.csv"', "Cache-Control": "no-store"},
    )


def _remind(db: Session, row: PolicyDocument, actor: User) -> ReminderOut:
    count = acks.notify_unaccepted(db, row, actor)
    db.commit()
    return ReminderOut(notified=count)


@system_router.get("", response_model=list[PolicySummaryOut])
def list_server_policies(current_user: User = Depends(require_server_admin), db: Session = Depends(get_db)) -> list[PolicySummaryOut]:
    """The server policies, the built-in slots first; a slot not yet written appears as an unset row (`id` null)."""
    rows = service.list_scope(db, None)
    current = service.current_versions(db, rows)
    by_key = {r.key: r for r in rows if r.key}
    slots = [
        _summary(by_key[k], current.get(by_key[k].id)) if k in by_key else PolicySummaryOut(
            id=None, key=k, title=title, state=PolicyState.DRAFT, effective_from=None, current_version=0,
            has_unpublished_changes=False, updated_at=None, requires_acknowledgement=False,
        )
        for k, title in service.SLOT_TITLES.items()
    ]
    return slots + [_summary(r, current.get(r.id)) for r in rows if not r.key]


@system_router.post("", response_model=PolicyOut, status_code=status.HTTP_201_CREATED)
def create_server_policy(body: PolicyIn, current_user: User = Depends(require_server_admin), db: Session = Depends(get_db)) -> PolicyOut:
    """Creates a draft server policy (a built-in slot with `key`, or any other policy with a title)."""
    row = service.create(
        db, organization_id=None, actor=current_user, key=body.key, title=body.title, body=body.body,
        effective_from=body.effective_from,
    )
    _apply_requirement(db, row, body, current_user)
    db.commit()
    return _out(db, row)


@system_router.get("/{policy_id}", response_model=PolicyOut)
def get_server_policy(policy_id: UUID, current_user: User = Depends(require_server_admin), db: Session = Depends(get_db)) -> PolicyOut:
    """A server policy with its working copy and version history."""
    return _out(db, service.get_in_scope(db, policy_id, None))


@system_router.put("/{policy_id}", response_model=PolicyOut)
def replace_server_policy(
    policy_id: UUID, body: PolicyIn, current_user: User = Depends(require_server_admin), db: Session = Depends(get_db),
) -> PolicyOut:
    """Replaces a server policy's working copy; readers keep seeing the published version until it is published."""
    row = service.get_in_scope(db, policy_id, None, lock=True)
    service.update(db, row, actor=current_user, title=body.title, body=body.body, effective_from=body.effective_from)
    _apply_requirement(db, row, body, current_user)
    db.commit()
    return _out(db, row)


@system_router.post("/{policy_id}/publish", response_model=PolicyOut)
def publish_server_policy(
    policy_id: UUID, body: PolicyPublishIn, current_user: User = Depends(require_server_admin), db: Session = Depends(get_db),
) -> PolicyOut:
    """Publishes the working copy as the next version."""
    row = service.get_in_scope(db, policy_id, None, lock=True)
    service.publish(db, row, actor=current_user, change_note=body.change_note)
    acks.notify_unaccepted(db, row, current_user)
    db.commit()
    return _out(db, row)


@system_router.post("/{policy_id}/unpublish", response_model=PolicyOut)
def unpublish_server_policy(policy_id: UUID, current_user: User = Depends(require_server_admin), db: Session = Depends(get_db)) -> PolicyOut:
    """Takes a server policy off the Policies page; every version is kept."""
    row = service.get_in_scope(db, policy_id, None, lock=True)
    service.unpublish(db, row, current_user)
    db.commit()
    return _out(db, row)


@system_router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server_policy(policy_id: UUID, current_user: User = Depends(require_server_admin), db: Session = Depends(get_db)) -> Response:
    """Deletes a server policy that is not a built-in slot, with its versions."""
    service.delete(db, service.get_in_scope(db, policy_id, None), current_user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@system_router.get("/{policy_id}/acknowledgements", response_model=AcknowledgementStatusOut)
def get_server_policy_acknowledgements(
    policy_id: UUID, current_user: User = Depends(require_server_admin), db: Session = Depends(get_db),
) -> AcknowledgementStatusOut:
    """Who has and has not accepted a server policy's current version."""
    return _status_out(db, service.get_in_scope(db, policy_id, None))


@system_router.get("/{policy_id}/acknowledgements/export")
def export_server_policy_acknowledgements(
    policy_id: UUID, current_user: User = Depends(require_server_admin), db: Session = Depends(get_db),
) -> Response:
    """The status of a server policy as a CSV (person, email, status, version and time)."""
    return _status_csv(db, service.get_in_scope(db, policy_id, None), current_user)


@system_router.post("/{policy_id}/acknowledgements/remind", response_model=ReminderOut)
def remind_server_policy(
    policy_id: UUID, current_user: User = Depends(require_server_admin), db: Session = Depends(get_db),
) -> ReminderOut:
    """Notifies everyone who has not accepted a server policy's current version."""
    return _remind(db, service.get_in_scope(db, policy_id, None), current_user)


@system_router.get("/{policy_id}/versions/{version}", response_model=PolicyVersionBodyOut)
def get_server_policy_version(
    policy_id: UUID, version: int, current_user: User = Depends(require_server_admin), db: Session = Depends(get_db),
) -> PolicyVersionBodyOut:
    """One published version with its text, for audit."""
    v = service.get_version(db, service.get_in_scope(db, policy_id, None), version)
    return PolicyVersionBodyOut(**_version_out(v).model_dump(), body=v.body)


# --- organisation ---------------------------------------------------------------------------------------


def _audience_out(db: Session, audiences: dict[UUID, list[PrincipalRef]], policy_id: UUID) -> list[PrincipalOut]:
    """The resolved audience of one policy (display names and member counts)."""
    refs = audiences.get(policy_id, [])
    labels = principal_labels(db, refs)
    return [labels[(r.type.value, r.id)] for r in refs]


def _org_out(db: Session, row: PolicyDocument) -> OrgPolicyOut:
    return OrgPolicyOut(**_out(db, row).model_dump(), audience=_audience_out(db, org_policies.audience_of(db, [row.id]), row.id))


@org_router.get("/settings", response_model=OrgPolicySettingsIO)
def get_org_policy_settings(
    organization_id: UUID, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> OrgPolicySettingsIO:
    """The organisation's policy settings, with the starter titles the add dialog suggests."""
    return OrgPolicySettingsIO(allow_links=org_policies.links_allowed(db, organization_id), starter_titles=list(org_policies.STARTER_TITLES))


@org_router.put("/settings", response_model=OrgPolicySettingsIO)
def replace_org_policy_settings(
    organization_id: UUID, body: OrgPolicySettingsIn, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> OrgPolicySettingsIO:
    """Chooses whether the organisation's policies may contain links."""
    org_policies.set_links_allowed(db, organization_id, body.allow_links, current_user)
    db.commit()
    return OrgPolicySettingsIO(allow_links=body.allow_links, starter_titles=list(org_policies.STARTER_TITLES))


@org_router.post("/audience-labels", response_model=list[PrincipalOut])
def resolve_org_policy_audience(
    organization_id: UUID, body: OrgPolicyAudienceLookupIn, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> list[PrincipalOut]:
    """Display names for people and groups picked for an audience that is not saved yet.

    Each entry must belong to the organisation (the rule `PUT` applies), so a name from another organisation is never returned.
    """
    for entry in body.audience:
        validate_principal(db, entry, organization_id=organization_id, project_id=None, field="audience")
    labels = principal_labels(db, body.audience)
    return [labels[(r.type.value, r.id)] for r in body.audience]


@org_router.get("", response_model=list[OrgPolicySummaryOut])
def list_org_policies(
    organization_id: UUID, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> list[OrgPolicySummaryOut]:
    """Every policy of the organisation, whatever its audience, by title."""
    rows = service.list_scope(db, organization_id)
    current = service.current_versions(db, rows)
    audiences = org_policies.audience_of(db, [r.id for r in rows])
    return [
        OrgPolicySummaryOut(**_summary(r, current.get(r.id)).model_dump(), audience=_audience_out(db, audiences, r.id)) for r in rows
    ]


@org_router.post("", response_model=OrgPolicyOut, status_code=status.HTTP_201_CREATED)
def create_org_policy(
    organization_id: UUID, body: OrgPolicyIn, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> OrgPolicyOut:
    """Creates a draft policy for the organisation (it has no built-in slots, so `key` is refused)."""
    row = service.create(
        db, organization_id=organization_id, actor=current_user, key=body.key, title=body.title, body=body.body,
        effective_from=body.effective_from, allow_links=org_policies.links_allowed(db, organization_id),
    )
    org_policies.set_audience(db, row, body.audience or [], current_user)
    _apply_requirement(db, row, body, current_user)
    db.commit()
    return _org_out(db, row)


@org_router.get("/{policy_id}", response_model=OrgPolicyOut)
def get_org_policy(
    organization_id: UUID, policy_id: UUID, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> OrgPolicyOut:
    """An organisation policy with its working copy, audience and version history."""
    return _org_out(db, service.get_in_scope(db, policy_id, organization_id))


@org_router.put("/{policy_id}", response_model=OrgPolicyOut)
def replace_org_policy(
    organization_id: UUID, policy_id: UUID, body: OrgPolicyIn, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> OrgPolicyOut:
    """Replaces the working copy (and the audience when sent); readers keep seeing the published version until it is published."""
    row = service.get_in_scope(db, policy_id, organization_id, lock=True)
    service.update(
        db, row, actor=current_user, title=body.title, body=body.body, effective_from=body.effective_from,
        allow_links=org_policies.links_allowed(db, organization_id),
    )
    if body.audience is not None:
        org_policies.set_audience(db, row, body.audience, current_user)
    _apply_requirement(db, row, body, current_user)
    db.commit()
    return _org_out(db, row)


@org_router.post("/{policy_id}/publish", response_model=OrgPolicyOut)
def publish_org_policy(
    organization_id: UUID, policy_id: UUID, body: OrgPolicyPublishIn,
    current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> OrgPolicyOut:
    """Publishes the working copy as the next version, telling its readers when `notify_members` is set."""
    row = service.get_in_scope(db, policy_id, organization_id, lock=True)
    org_policies.check_publishable(db, row)
    version = service.publish(db, row, actor=current_user, change_note=body.change_note)
    if row.requires_acknowledgement:
        # Asking for acceptance is the notification for a required policy; one message per person, not two.
        acks.notify_unaccepted(db, row, current_user)
    elif body.notify_members:
        org_policies.notify_audience(db, row, version, current_user)
    db.commit()
    return _org_out(db, row)


@org_router.post("/{policy_id}/unpublish", response_model=OrgPolicyOut)
def unpublish_org_policy(
    organization_id: UUID, policy_id: UUID, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> OrgPolicyOut:
    """Takes an organisation policy off its readers' page; every version is kept."""
    row = service.get_in_scope(db, policy_id, organization_id, lock=True)
    service.unpublish(db, row, current_user)
    db.commit()
    return _org_out(db, row)


@org_router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_org_policy(
    organization_id: UUID, policy_id: UUID, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> Response:
    """Deletes an organisation policy with its versions and audience."""
    service.delete(db, service.get_in_scope(db, policy_id, organization_id), current_user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@org_router.get("/{policy_id}/acknowledgements", response_model=AcknowledgementStatusOut)
def get_org_policy_acknowledgements(
    organization_id: UUID, policy_id: UUID, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> AcknowledgementStatusOut:
    """Who has and has not accepted an organisation policy's current version."""
    return _status_out(db, service.get_in_scope(db, policy_id, organization_id))


@org_router.get("/{policy_id}/acknowledgements/export")
def export_org_policy_acknowledgements(
    organization_id: UUID, policy_id: UUID, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> Response:
    """The status of an organisation policy as a CSV (person, email, status, version and time)."""
    return _status_csv(db, service.get_in_scope(db, policy_id, organization_id), current_user)


@org_router.post("/{policy_id}/acknowledgements/remind", response_model=ReminderOut)
def remind_org_policy(
    organization_id: UUID, policy_id: UUID, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> ReminderOut:
    """Notifies everyone who has not accepted an organisation policy's current version."""
    return _remind(db, service.get_in_scope(db, policy_id, organization_id), current_user)


@org_router.get("/{policy_id}/versions/{version}", response_model=PolicyVersionBodyOut)
def get_org_policy_version(
    organization_id: UUID, policy_id: UUID, version: int, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> PolicyVersionBodyOut:
    """One published version with its text, for audit."""
    v = service.get_version(db, service.get_in_scope(db, policy_id, organization_id), version)
    return PolicyVersionBodyOut(**_version_out(v).model_dump(), body=v.body)


# --- members --------------------------------------------------------------------------------------------


def _member_summary(item: org_policies.ReaderPolicy) -> MemberPolicySummaryOut:
    return MemberPolicySummaryOut(
        id=item.row.id, organization_id=item.organization.id, organization_name=item.organization.name,
        title=item.version.title, effective_from=item.version.effective_from, version=item.version.version,
        published_at=item.version.published_at,
    )


@member_router.get("", response_model=list[MemberPolicySummaryOut])
def list_my_policies(
    response: Response, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> list[MemberPolicySummaryOut]:
    """The published policies of the caller's organisations that the caller may read."""
    _no_store(response)
    required = {p.row.id: p.accepted for p in acks.applicable(db, current_user)} if acks.any_required(db) else {}
    return [
        _member_summary(item).model_copy(update={
            "requires_acknowledgement": item.row.id in required, "acknowledged": required.get(item.row.id, False),
        })
        for item in org_policies.published_for(db, current_user)
    ]


@member_router.get("/pending", response_model=list[PendingPolicyOut])
def list_pending_policies(
    response: Response, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> list[PendingPolicyOut]:
    """The server and organisation policies the caller must accept, with their text (empty when none)."""
    _no_store(response)
    if not acks.any_required(db):
        return []
    return [
        PendingPolicyOut(
            id=p.row.id, organization_id=p.organization.id if p.organization else None,
            organization_name=p.organization.name if p.organization else None, title=p.version.title,
            effective_from=p.version.effective_from, version=p.version.version, published_at=p.version.published_at,
            body=p.version.body,
        )
        for p in acks.pending(db, current_user)
    ]


@member_router.post("/{policy_id}/acknowledge", response_model=AcknowledgementOut)
def acknowledge_policy(
    policy_id: UUID, body: AcknowledgeIn, current_user: User = Depends(get_current_session_user), db: Session = Depends(get_db),
) -> AcknowledgementOut:
    """Records that the caller read and accepted the given version of a required policy.

    Interactive sessions only: an access token is a headless credential and cannot accept on a person's behalf.
    """
    record = acks.acknowledge(db, current_user, policy_id, body.version)
    db.commit()
    return AcknowledgementOut(policy_id=record.policy_id, version=record.version, acknowledged_at=record.acknowledged_at)


@member_router.get("/{policy_id}", response_model=MemberPolicyOut)
def get_my_policy(
    policy_id: UUID, response: Response, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> MemberPolicyOut:
    """One published organisation policy with its text (404 for one the caller may not read)."""
    _no_store(response)
    item = org_policies.reader_policy(db, current_user, policy_id)
    return MemberPolicyOut(**_member_summary(item).model_dump(), body=item.version.body)


# --- public ---------------------------------------------------------------------------------------------


def _no_store(response: Response) -> None:
    """Published text can be withdrawn at any time, so no shared cache may keep it."""
    response.headers["Cache-Control"] = "no-store"


@public_router.get("", response_model=list[PublicPolicySummaryOut])
def list_public_policies(
    response: Response, client_ip: str = Depends(get_client_ip), db: Session = Depends(get_db),
) -> list[PublicPolicySummaryOut]:
    """Public: the published server policies (unauthenticated, rate-limited per address)."""
    service.enforce_public_rate_limit(client_ip)
    _no_store(response)
    return [
        PublicPolicySummaryOut(
            id=r.id, key=r.key, title=v.title, effective_from=v.effective_from, version=v.version, published_at=v.published_at,
        )
        for r, v in service.published_server_policies(db)
    ]


@public_router.get("/{policy_id}", response_model=PublicPolicyOut)
def get_public_policy(
    policy_id: UUID, response: Response, client_ip: str = Depends(get_client_ip), db: Session = Depends(get_db),
) -> PublicPolicyOut:
    """Public: one published server policy with its text (an unpublished or unknown policy is a 404)."""
    service.enforce_public_rate_limit(client_ip)
    _no_store(response)
    r, v = service.published_server_policy(db, policy_id)
    return PublicPolicyOut(
        id=r.id, key=r.key, title=v.title, effective_from=v.effective_from, version=v.version, published_at=v.published_at,
        body=v.body,
    )
