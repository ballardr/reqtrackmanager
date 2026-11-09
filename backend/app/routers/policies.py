"""
Module: routers.policies

Policies (written documents such as a privacy policy):
- `/api/v1/system/policies`: server administrators write, publish and retire server policies.
- `GET /api/v1/public/policies` and `/{id}`: public, rate-limited; the published server policies.

Authorisation: scope is enforced in `services.policies` (a policy of another scope is a 404). The public read
returns only published content (never the author, working copy, change note or an unpublished policy).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip
from app.models.policy import PolicyDocument, PolicyDocumentVersion, PolicyState
from app.models.user import User
from app.schemas.policies import (
    PolicyIn,
    PolicyOut,
    PolicyPublishIn,
    PolicySummaryOut,
    PolicyVersionBodyOut,
    PolicyVersionOut,
    PublicPolicyOut,
    PublicPolicySummaryOut,
)
from app.services import policies as service
from app.services.rbac import require_server_admin

system_router = APIRouter(prefix="/api/v1/system/policies", tags=["policies"])
public_router = APIRouter(prefix="/api/v1/public/policies", tags=["policies"])


def _summary(row: PolicyDocument, current: PolicyDocumentVersion | None) -> PolicySummaryOut:
    return PolicySummaryOut(
        id=row.id, key=row.key, title=row.title, state=row.state, effective_from=row.effective_from,
        current_version=row.current_version, has_unpublished_changes=service.has_unpublished_changes(row, current),
        updated_at=row.updated_at,
    )


def _version_out(v: PolicyDocumentVersion) -> PolicyVersionOut:
    return PolicyVersionOut(
        version=v.version, title=v.title, effective_from=v.effective_from, published_at=v.published_at, change_note=v.change_note,
    )


def _out(db: Session, row: PolicyDocument) -> PolicyOut:
    history = service.versions(db, row)
    current = next((v for v in history if v.version == row.current_version), None)
    return PolicyOut(**_summary(row, current).model_dump(), body=row.body, versions=[_version_out(v) for v in history])


@system_router.get("", response_model=list[PolicySummaryOut])
def list_server_policies(current_user: User = Depends(require_server_admin), db: Session = Depends(get_db)) -> list[PolicySummaryOut]:
    """The server policies, the built-in slots first; a slot not yet written appears as an unset row (`id` null)."""
    rows = service.list_scope(db, None)
    current = service.current_versions(db, rows)
    by_key = {r.key: r for r in rows if r.key}
    slots = [
        _summary(by_key[k], current.get(by_key[k].id)) if k in by_key else PolicySummaryOut(
            id=None, key=k, title=title, state=PolicyState.DRAFT, effective_from=None, current_version=0,
            has_unpublished_changes=False, updated_at=None,
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
    db.commit()
    return _out(db, row)


@system_router.post("/{policy_id}/publish", response_model=PolicyOut)
def publish_server_policy(
    policy_id: UUID, body: PolicyPublishIn, current_user: User = Depends(require_server_admin), db: Session = Depends(get_db),
) -> PolicyOut:
    """Publishes the working copy as the next version."""
    row = service.get_in_scope(db, policy_id, None, lock=True)
    service.publish(db, row, actor=current_user, change_note=body.change_note)
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


@system_router.get("/{policy_id}/versions/{version}", response_model=PolicyVersionBodyOut)
def get_server_policy_version(
    policy_id: UUID, version: int, current_user: User = Depends(require_server_admin), db: Session = Depends(get_db),
) -> PolicyVersionBodyOut:
    """One published version with its text, for audit."""
    v = service.get_version(db, service.get_in_scope(db, policy_id, None), version)
    return PolicyVersionBodyOut(**_version_out(v).model_dump(), body=v.body)


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
