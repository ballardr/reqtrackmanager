"""
Module: routers.scim

Inbound SCIM 2.0 (RFC 7643/7644) provisioning — lets an IdP push user/group
membership changes directly, on its own schedule, with no user login
required. This is the purpose-built alternative to
`services/oidc_provisioning.py`'s claims-based sync (`sync_org_groups_from_claims`),
which only ever runs at login time and can't promptly deprovision someone
who stops logging in. Per-organisation bearer token auth
(`Organization.scim_token_hash`/`scim_token_prefix`, managed via
`routers/orgs.py`'s `/scim-token` endpoints), entirely independent of any
user session.

A SCIM Group's `id` is this app's own `OrgGroup.id`, and a SCIM User's `id`
is this app's own `User.id` — the IdP stores whatever `id` a `POST` returns
and addresses that exact resource on every later call, so no separate
external-id mapping table is needed. Group membership sync therefore
operates directly on `OrgGroupMember` rows with `user_id` set — never
`member_org_group_id` (nested-group) edges, which are structural,
admin-managed relationships, not something an IdP's group roster should be
able to rearrange.

Deliberately a pragmatic subset of the spec, not full RFC 7644 compliance
(documented candidly, not hidden — see docs/enterprise-integration.md):
- Filter support is limited to a single `attr eq "value"` expression,
  covering the `userName eq`/`emails.value eq` queries real IdP SCIM
  clients (Okta, Azure AD, Google Workspace) send in practice — no
  AND/OR/complex filter grammar.
- PATCH supports `active`/`displayName` replace on Users and
  `members` add/remove on Groups — the operations those same IdPs actually
  send for deprovisioning and group-membership sync — not arbitrary path
  expressions.
- No Bulk operations, no ETags/versioning, no schema extensions.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import OrgRole
from app.models.organization import Organization, OrgGroup, OrgGroupMember, UserOrgRole
from app.models.project import ProjectGroupMember
from app.models.user import User
from app.security import hash_pat
from app.services.audit import log_event
from app.services.rbac import get_effective_org_roles

router = APIRouter(prefix="/scim/v2", tags=["scim"])

SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCIM_LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"

_ATTR_CHARSET = re.compile(r'^[\w.\[\] "=]+$')


def require_scim_org(request: Request, db: Session = Depends(get_db)) -> Organization:
    """Resolves the calling organisation from a SCIM bearer token.

    Deliberately distinct from every other auth dependency in this app
    (`deps.get_current_user*`) — a SCIM request authenticates as an
    *organisation*, via a token an org admin generated, never as any
    individual `User`/session.

    Raises:
        HTTPException: 401 if the token is missing/invalid, 403 if the
            resolved organisation has been disabled.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token.")
    raw_token = auth_header[7:].strip()
    if not raw_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token.")
    org = db.scalar(select(Organization).where(Organization.scim_token_hash == hash_pat(raw_token)))
    if org is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid SCIM token.")
    if not org.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This organisation has been disabled.")
    return org


def _parse_simple_eq_filter(filter_param: str | None) -> tuple[str, str] | None:
    """Parses the single `attr eq "value"` filter shape real SCIM clients
    send for user/group lookups — see module docstring for the scope
    limitation.

    Deliberately not a `(attr)\\s+eq\\s+"(value)"`-shaped regex over the
    whole `filter_param`, in either a single combined pattern or a
    `search()` for just the trailing `eq "value"` half: `attr` itself can
    legitimately contain its own `eq "..."` (the bracket-filter shape this
    module accepts, `emails[type eq "work"].value`), and `filter_param` is
    attacker-controlled (any bearer-token holder can send it) — a combined
    pattern has to backtrack over every candidate split between attr's
    embedded `eq` and the real trailing one, and even a `search()` for only
    `\\s+eq\\s+"..."` is *itself* polynomial-time on a long run of
    whitespace containing no "eq" at all (every starting position
    backtracks its own `\\s+` before failing — the same CodeQL
    py/polynomial-redos shape, just moved rather than removed). Finding the
    same attr/value split with plain string operations (`rfind`/slicing)
    instead avoids backtracking entirely, in genuinely linear time.
    """
    if not filter_param:
        return None
    s = filter_param.strip()
    if s.endswith("]"):
        s = s[:-1].rstrip()
    # The value is whatever's between the last two quotes — the grammar
    # (`"([^"]*)"`, no escaping) never lets the value itself contain a `"`.
    if len(s) < 2 or s[-1] != '"':
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported filter expression.")
    end_quote = len(s) - 1
    start_quote = s.rfind('"', 0, end_quote)
    # At least one whitespace char must separate "eq" from the opening
    # quote (hardening pass, 2026-09) — `before = s[:start_quote].rstrip()`
    # alone would accept a zero-whitespace gap too (e.g. `eq"active"`,
    # never valid per SCIM's grammar or the original `\s+eq\s+"..."` regex
    # this function replaced), since rstrip() has nothing to strip when
    # the quote immediately follows "eq". Checked before rstripping so a
    # missing gap is rejected regardless of how much whitespace precedes
    # the "eq" token itself.
    before_raw = s[:start_quote] if start_quote != -1 else ""
    if start_quote == -1 or not before_raw or not before_raw[-1].isspace():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported filter expression.")
    before = before_raw.rstrip()
    # "eq" must be its own token: at least one char of attr, then
    # whitespace, then "eq", immediately before the opening quote.
    if len(before) < 3 or before[-2:].lower() != "eq" or not before[-3].isspace():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported filter expression.")
    value = s[start_quote + 1 : end_quote]
    attr = before[:-3].rstrip()
    if not attr or not _ATTR_CHARSET.match(attr):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported filter expression.")
    return attr.lower(), value


def _user_to_scim(user: User) -> dict[str, Any]:
    return {
        "schemas": [SCIM_USER_SCHEMA],
        "id": str(user.id),
        "userName": user.email,
        "displayName": user.display_name,
        "name": {"formatted": user.display_name},
        "emails": [{"value": user.email, "primary": True}],
        "active": user.is_active and not user.is_archived,
        "meta": {"resourceType": "User"},
    }


def _group_to_scim(db: Session, group: OrgGroup) -> dict[str, Any]:
    member_ids = db.scalars(
        select(OrgGroupMember.user_id).where(
            OrgGroupMember.org_group_id == group.id, OrgGroupMember.user_id.is_not(None)
        )
    ).all()
    return {
        "schemas": [SCIM_GROUP_SCHEMA],
        "id": str(group.id),
        "displayName": group.name,
        "members": [{"value": str(uid)} for uid in member_ids],
        "meta": {"resourceType": "Group"},
    }


def _list_response(resources: list[dict[str, Any]], *, start_index: int, total: int) -> dict[str, Any]:
    return {
        "schemas": [SCIM_LIST_SCHEMA],
        "totalResults": total,
        "startIndex": start_index,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }


def _get_org_user(db: Session, org: Organization, user_id: UUID) -> User:
    """Loads a User and 404s unless they actually belong to `org` — without
    this, a SCIM token for org A could read/modify any user in the entire
    deployment by guessing/enumerating ids."""
    user = db.get(User, user_id)
    if user is None or not get_effective_org_roles(db, user.id, org.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    return user


def _get_org_group(db: Session, org: Organization, group_id: UUID) -> OrgGroup:
    group = db.get(OrgGroup, group_id)
    if group is None or group.organization_id != org.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found.")
    return group


def _parse_uuid(value: Any) -> UUID | None:
    """Parses a SCIM member `value` into a UUID, or `None` if it isn't one.

    A real IdP only ever echoes back an id this app itself issued (the
    `id` returned from a prior `POST`/`GET`), so this should never actually
    fire — but the request body is untyped (`dict[str, Any]`), so a
    malformed or hand-crafted request previously hit a raw `UUID(...)`
    call and 500ed instead of getting a clean rejection. Callers skip a
    bad entry rather than fail the whole request, matching
    `_add_group_member`'s existing "silently skip a member id that isn't
    a real org member" tolerance for this same untrusted list.
    """
    if not value:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


@router.get("/ServiceProviderConfig")
def service_provider_config() -> dict[str, Any]:
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "Bearer Token",
                "description": "Per-organisation SCIM bearer token, generated in Organisation Admin.",
            }
        ],
    }


@router.get("/ResourceTypes")
def resource_types() -> list[dict[str, Any]]:
    return [
        {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
            "id": "User", "name": "User", "endpoint": "/Users", "schema": SCIM_USER_SCHEMA,
        },
        {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
            "id": "Group", "name": "Group", "endpoint": "/Groups", "schema": SCIM_GROUP_SCHEMA,
        },
    ]


# --- Users -------------------------------------------------------------


@router.get("/Users")
def list_users(
    filter: str | None = Query(None),
    startIndex: int = Query(1, ge=1),
    count: int = Query(100, ge=1, le=200),
    org: Organization = Depends(require_scim_org),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_user_ids = set(db.scalars(select(UserOrgRole.user_id).where(UserOrgRole.organization_id == org.id)).all())
    query = select(User).where(User.id.in_(org_user_ids))
    parsed = _parse_simple_eq_filter(filter)
    if parsed:
        attr, value = parsed
        if attr in ("username", "emails.value", 'emails[type eq "work"].value'):
            query = query.where(User.email == value.strip().lower())
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unsupported filter attribute: {attr}")
    all_users = db.scalars(query.order_by(User.email)).all()
    page = all_users[startIndex - 1 : startIndex - 1 + count]
    return _list_response([_user_to_scim(u) for u in page], start_index=startIndex, total=len(all_users))


@router.post("/Users", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: dict[str, Any] = Body(...), org: Organization = Depends(require_scim_org), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Provisions a user into this organisation — `find-or-create` by
    email, matching `services.oidc_provisioning.find_or_provision_user`'s
    reuse-by-email approach, but without an email-verification gate: the
    entire SCIM channel is already privileged (only reachable with a token
    an org admin explicitly generated), unlike OIDC's public login flow
    where any caller could otherwise claim an arbitrary email.

    Grants baseline `OrgRole.MEMBER` if the resolved user holds no role in
    this org yet — a SCIM `Users` resource is inherently org-scoped, so
    "provisioned into this org" already implies membership; role
    elevation beyond that happens via `sync_org_group_mappings`-managed
    OIDC claims or group sync, not here.
    """
    email = payload.get("userName") or next(
        (e.get("value") for e in payload.get("emails", []) if isinstance(e, dict) and e.get("value")), None
    )
    if not email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "userName or an email is required.")
    email = str(email).strip().lower()
    display_name = payload.get("displayName") or (payload.get("name") or {}).get("formatted") or email.split("@")[0]

    user = db.scalar(select(User).where(User.email == email))
    if user is not None and user.is_banned:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been banned and cannot be provisioned.")
    if user is None:
        user = User(email=email, display_name=display_name, auth_backend="scim", password_hash=None)
        db.add(user)
        db.flush()
    if not get_effective_org_roles(db, user.id, org.id):
        db.add(UserOrgRole(user_id=user.id, organization_id=org.id, role=OrgRole.MEMBER))
    log_event(
        db, entity_type="user", entity_id=user.id, action="scim_provisioned", actor_id=None,
        organization_id=org.id, detail={"email": email},
    )
    db.commit()
    return _user_to_scim(user)


@router.get("/Users/{user_id}")
def get_user(user_id: UUID, org: Organization = Depends(require_scim_org), db: Session = Depends(get_db)) -> dict[str, Any]:
    return _user_to_scim(_get_org_user(db, org, user_id))


@router.put("/Users/{user_id}")
def replace_user(
    user_id: UUID, payload: dict[str, Any] = Body(...),
    org: Organization = Depends(require_scim_org), db: Session = Depends(get_db),
) -> dict[str, Any]:
    user = _get_org_user(db, org, user_id)
    if payload.get("displayName"):
        user.display_name = payload["displayName"]
    if "active" in payload:
        user.is_active = bool(payload["active"])
    log_event(db, entity_type="user", entity_id=user.id, action="scim_replaced", actor_id=None, organization_id=org.id)
    db.commit()
    return _user_to_scim(user)


@router.patch("/Users/{user_id}")
def patch_user(
    user_id: UUID, payload: dict[str, Any] = Body(...),
    org: Organization = Depends(require_scim_org), db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Applies the subset of SCIM PATCH operations real IdPs send for a
    user: `active` (deactivation, C-U-04 — never a hard delete) and
    `displayName`. See module docstring for the scope limitation."""
    user = _get_org_user(db, org, user_id)
    for op in payload.get("Operations", []):
        value = op.get("value")
        path = (op.get("path") or "").strip()
        if path == "active" or (not path and isinstance(value, dict) and "active" in value):
            user.is_active = bool(value if not isinstance(value, dict) else value.get("active"))
        elif path == "displayName" and isinstance(value, str):
            user.display_name = value
        elif not path and isinstance(value, dict) and "displayName" in value:
            user.display_name = value["displayName"]
    log_event(db, entity_type="user", entity_id=user.id, action="scim_patched", actor_id=None, organization_id=org.id)
    db.commit()
    return _user_to_scim(user)


@router.delete("/Users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: UUID, org: Organization = Depends(require_scim_org), db: Session = Depends(get_db)):
    """Deactivates rather than hard-deletes (C-U-04/C-U-05) — consistent
    with every other user-removal path in this app."""
    user = _get_org_user(db, org, user_id)
    user.is_active = False
    log_event(db, entity_type="user", entity_id=user.id, action="scim_deactivated", actor_id=None, organization_id=org.id)
    db.commit()


# --- Groups --------------------------------------------------------------


@router.get("/Groups")
def list_groups(
    filter: str | None = Query(None),
    startIndex: int = Query(1, ge=1),
    count: int = Query(100, ge=1, le=200),
    org: Organization = Depends(require_scim_org),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    query = select(OrgGroup).where(OrgGroup.organization_id == org.id)
    parsed = _parse_simple_eq_filter(filter)
    if parsed:
        attr, value = parsed
        if attr == "displayname":
            query = query.where(OrgGroup.name == value)
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unsupported filter attribute: {attr}")
    all_groups = db.scalars(query.order_by(OrgGroup.name)).all()
    page = all_groups[startIndex - 1 : startIndex - 1 + count]
    return _list_response([_group_to_scim(db, g) for g in page], start_index=startIndex, total=len(all_groups))


@router.post("/Groups", status_code=status.HTTP_201_CREATED)
def create_group(
    payload: dict[str, Any] = Body(...), org: Organization = Depends(require_scim_org), db: Session = Depends(get_db)
) -> dict[str, Any]:
    display_name = payload.get("displayName")
    if not display_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "displayName is required.")
    group = OrgGroup(organization_id=org.id, name=display_name)
    db.add(group)
    db.flush()
    for member in payload.get("members", []) or []:
        member_id = _parse_uuid(member.get("value")) if isinstance(member, dict) else None
        if member_id and get_effective_org_roles(db, member_id, org.id):
            db.add(OrgGroupMember(org_group_id=group.id, user_id=member_id))
    log_event(
        db, entity_type="org_group", entity_id=group.id, action="scim_created", actor_id=None,
        organization_id=org.id, detail={"name": display_name},
    )
    db.commit()
    return _group_to_scim(db, group)


@router.get("/Groups/{group_id}")
def get_group(group_id: UUID, org: Organization = Depends(require_scim_org), db: Session = Depends(get_db)) -> dict[str, Any]:
    return _group_to_scim(db, _get_org_group(db, org, group_id))


def _add_group_member(db: Session, org: Organization, group: OrgGroup, user_id: UUID) -> None:
    if not get_effective_org_roles(db, user_id, org.id):
        return  # silently skip a member id that isn't (or is no longer) a real org member
    existing = db.scalar(
        select(OrgGroupMember).where(OrgGroupMember.org_group_id == group.id, OrgGroupMember.user_id == user_id)
    )
    if existing is None:
        db.add(OrgGroupMember(org_group_id=group.id, user_id=user_id))


def _remove_group_member(db: Session, group: OrgGroup, user_id: UUID) -> None:
    db.execute(
        OrgGroupMember.__table__.delete().where(
            OrgGroupMember.org_group_id == group.id, OrgGroupMember.user_id == user_id
        )
    )


@router.put("/Groups/{group_id}")
def replace_group(
    group_id: UUID, payload: dict[str, Any] = Body(...),
    org: Organization = Depends(require_scim_org), db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Full replace: renames the group (if `displayName` given) and sets
    membership to exactly the given `members` list — added/removed as
    needed, same as a PATCH `members` replace would net out to."""
    group = _get_org_group(db, org, group_id)
    if payload.get("displayName"):
        group.name = payload["displayName"]
    if "members" in payload:
        desired = {
            parsed
            for m in (payload.get("members") or [])
            if isinstance(m, dict) and (parsed := _parse_uuid(m.get("value"))) is not None
        }
        current = set(
            db.scalars(
                select(OrgGroupMember.user_id).where(
                    OrgGroupMember.org_group_id == group.id, OrgGroupMember.user_id.is_not(None)
                )
            ).all()
        )
        for user_id in desired - current:
            _add_group_member(db, org, group, user_id)
        for user_id in current - desired:
            _remove_group_member(db, group, user_id)
    log_event(db, entity_type="org_group", entity_id=group.id, action="scim_replaced", actor_id=None, organization_id=org.id)
    db.commit()
    return _group_to_scim(db, group)


_MEMBER_VALUE_EQ = re.compile(r'value\s+eq\s+"([^"]+)"', re.IGNORECASE)


@router.patch("/Groups/{group_id}")
def patch_group(
    group_id: UUID, payload: dict[str, Any] = Body(...),
    org: Organization = Depends(require_scim_org), db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Applies the SCIM PATCH shapes real IdPs send for group-membership
    sync: `add`/`remove` with `path: "members"` and a `value` list of
    `{"value": "<user-id>"}` entries, or `remove` with a single-member
    filter path (`members[value eq "<user-id>"]`) — see module docstring
    for the scope limitation. Only ever touches `user_id`-keyed rows;
    nested-group edges (`member_org_group_id`) are never affected."""
    group = _get_org_group(db, org, group_id)
    for op in payload.get("Operations", []):
        op_name = (op.get("op") or "").lower()
        path = (op.get("path") or "").strip()
        if path == "displayName" and isinstance(op.get("value"), str):
            group.name = op["value"]
            continue
        if not path.startswith("members"):
            continue
        single_match = _MEMBER_VALUE_EQ.search(path)
        if single_match:
            target_ids = [parsed] if (parsed := _parse_uuid(single_match.group(1))) is not None else []
        else:
            target_ids = [
                parsed
                for m in (op.get("value") or [])
                if isinstance(m, dict) and (parsed := _parse_uuid(m.get("value"))) is not None
            ]
        for user_id in target_ids:
            if op_name == "add":
                _add_group_member(db, org, group, user_id)
            elif op_name == "remove":
                _remove_group_member(db, group, user_id)
    log_event(db, entity_type="org_group", entity_id=group.id, action="scim_patched", actor_id=None, organization_id=org.id)
    db.commit()
    return _group_to_scim(db, group)


@router.delete("/Groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(group_id: UUID, org: Organization = Depends(require_scim_org), db: Session = Depends(get_db)):
    """Deletes an org group. `OrgGroupMember`/`ProjectGroupMember` rows
    referencing it all cascade at the database level (`ondelete="CASCADE"`
    on each FK to `org_groups.id`) — this is the only group-deletion path
    in the app at all (no equivalent UI/API exists yet for a human org
    admin), so an IdP routinely deleting/recreating one of its groups can
    silently revoke whatever project access this group granted through
    nesting into a `ProjectGroup`, or drop it as another group's own
    nested member, with nothing about *that* recorded beyond "a group was
    deleted."

    Hardening-review finding: the log event only recorded the group's own
    id/name, not what its removal actually cascaded into — the same
    "record what changed, not just that something happened" gap the
    merge-import audit-provenance hardening pass fixed for
    `merge_org_bundle` (see docs/decisions.md). Fixed by capturing the
    affected `ProjectGroup`/parent-`OrgGroup` ids *before* the cascade
    runs and recording them in the event detail, so "a project's access
    just changed and nobody knows why" is answerable from the audit log
    alone.
    """
    group = _get_org_group(db, org, group_id)
    affected_project_group_ids = list(
        db.scalars(select(ProjectGroupMember.project_group_id).where(ProjectGroupMember.org_group_id == group.id)).all()
    )
    was_nested_inside_org_group_ids = list(
        db.scalars(select(OrgGroupMember.org_group_id).where(OrgGroupMember.member_org_group_id == group.id)).all()
    )
    db.execute(OrgGroupMember.__table__.delete().where(OrgGroupMember.org_group_id == group.id))
    db.execute(OrgGroupMember.__table__.delete().where(OrgGroupMember.member_org_group_id == group.id))
    log_event(
        db, entity_type="org_group", entity_id=group.id, action="scim_deleted", actor_id=None, organization_id=org.id,
        detail={
            "name": group.name,
            "affected_project_group_ids": [str(i) for i in affected_project_group_ids],
            "was_nested_inside_org_group_ids": [str(i) for i in was_nested_inside_org_group_ids],
        },
    )
    db.delete(group)
    db.commit()
