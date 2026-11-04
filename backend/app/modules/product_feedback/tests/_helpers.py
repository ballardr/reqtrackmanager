"""Shared helpers for the Product Feedback module's tests: org/project setup with the module enabled, member and
role grants, and request builders."""

from __future__ import annotations

import uuid

from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login

MODULE_KEY = "product_feedback"


def project_base(project_id) -> str:
    return f"/api/v1/projects/{project_id}/modules/{MODULE_KEY}"


def org_base(org_id) -> str:
    return f"/api/v1/orgs/{org_id}/modules/{MODULE_KEY}"


def enable_module(client, token, org_id) -> None:
    resp = client.put(f"/api/v1/orgs/{org_id}/modules/{MODULE_KEY}", json={"enabled": True}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def set_org_inbox(client, token, org_id, enabled: bool) -> None:
    """Switches the organisation's request inbox on or off (the `organization_requests` sub-component)."""
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{MODULE_KEY}/subcomponents/organization_requests",
        json={"enabled": enabled}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def setup(client, admin_token, org_name: str):
    """An org with a real admin, a project, and the module enabled."""
    org, token = create_org_admin_in(client, admin_token, org_name)
    enable_module(client, token, org["id"])
    return org, create_project(client, token, org["id"], f"{org_name} Project"), token


def add_member(client, org_admin_token, org_id, project_id, email) -> tuple[str, str]:
    """A plain project member; returns `(user id, token)`."""
    user_id = create_org_user(client, org_admin_token, org_id, email)
    resp = client.post(
        f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": "member"}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 204, resp.text
    return user_id, login(client, email, "Password123!")


def grant_project_role(client, token, project_id, user_id, role_key) -> None:
    resp = client.post(
        f"/api/v1/projects/{project_id}/members/{user_id}/module-roles",
        json={"module_key": MODULE_KEY, "role_key": role_key}, headers=auth_headers(token),
    )
    assert resp.status_code == 204, resp.text


def grant_org_role(client, token, org_id, user_id, role_key) -> None:
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users/{user_id}/module-roles",
        json={"module_key": MODULE_KEY, "role_key": role_key}, headers=auth_headers(token),
    )
    assert resp.status_code == 204, resp.text


def create_request(client, token, project_id, **extra) -> dict:
    payload = {"title": "Export this list", "description": "Let me export the list as a spreadsheet.", **extra}
    resp = client.post(project_base(project_id) + "/requests", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def create_inbox_request(client, token, org_id, **extra) -> dict:
    payload = {"title": "Dark mode", "description": "Please add a dark mode.", **extra}
    resp = client.post(org_base(org_id) + "/requests", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def transition(client, token, base: str, request_id, status: str, comment: str = ""):
    return client.post(
        f"{base}/requests/{request_id}/transition", json={"status": status, "comment": comment}, headers=auth_headers(token),
    )


def user_ref(user_id: str) -> dict:
    """A user as an `owner` principal reference."""
    return {"type": "user", "id": user_id}


# --- Requesters (Module 2 records) and links ---------------------------------

STAKEHOLDERS = "modules/stakeholders"


def enable_stakeholders(client, token, org_id) -> None:
    """Enables Stakeholders & Personas for the organisation (Product Feedback's requesters live there)."""
    resp = client.put(f"/api/v1/orgs/{org_id}/{STAKEHOLDERS}", json={"enabled": True}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def setup_with_people(client, admin_token, org_name: str):
    """`setup`, plus the Stakeholders & Personas module enabled."""
    org, project, token = setup(client, admin_token, org_name)
    enable_stakeholders(client, token, org["id"])
    return org, project, token


def create_stakeholder(client, token, project_id, name, *, influence: str | None = None, org_id=None) -> dict:
    """A project stakeholder, optionally rated on the Influence axis (`influence` is the level name)."""
    payload = {"name": name}
    if influence is not None:
        scheme = client.get(f"/api/v1/orgs/{org_id}/scoring-schemes/stakeholder", headers=auth_headers(token)).json()
        axis = next(a for a in scheme["axes"] if a["key"] == "influence")
        payload["influence_level_id"] = next(lvl["id"] for lvl in axis["levels"] if lvl["name"] == influence)
    resp = client.post(f"/api/v1/projects/{project_id}/{STAKEHOLDERS}/stakeholders", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def create_persona(client, token, project_id, name, *, weight: float | None = None) -> dict:
    """A project persona with an optional weight."""
    payload = {"name": name, **({"weight": weight} if weight is not None else {})}
    resp = client.post(f"/api/v1/projects/{project_id}/{STAKEHOLDERS}/personas", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def create_engagement(client, token, project_id, title="Workshop", *, stakeholder_ids=(), persona_ids=()) -> dict:
    """An engagement with the given participants and covered personas."""
    resp = client.post(
        f"/api/v1/projects/{project_id}/{STAKEHOLDERS}/engagements",
        json={
            "title": title, "channel": "workshop", "engagement_date": "2026-11-01",
            "stakeholder_ids": list(stakeholder_ids), "persona_ids": list(persona_ids),
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def requested_by_type_id(client, token, org_id) -> str:
    """The organisation's "Requested by" link type id (listing seeds module types)."""
    rows = client.get(f"/api/v1/orgs/{org_id}/link-types", headers=auth_headers(token)).json()
    return next(row["id"] for row in rows if row["forward_name"] == "Requested by")


def add_requester(client, token, org_id, project_id, request_id, other_type, other_id):
    """POSTs the generic link endpoint from the request's page: the request is "Requested by" the other record."""
    return client.post(
        f"/api/v1/projects/{project_id}/artefacts/enhancement_request/{request_id}/links",
        json={
            "link_type_id": requested_by_type_id(client, token, org_id), "direction": "outgoing",
            "other_type": other_type, "other_id": other_id,
        },
        headers=auth_headers(token),
    )


def get_request(client, token, project_id, request_id) -> dict:
    resp = client.get(f"{project_base(project_id)}/requests/{request_id}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def get_demand(client, token, project_id, request_id) -> dict:
    resp = client.get(f"{project_base(project_id)}/requests/{request_id}/demand", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- Problems and work (Pain Points, Requirements) and closing the loop ------


def enable_other_module(client, token, org_id, module_key: str) -> None:
    """Enables another module for the organisation (Context & Strategy holds the Pain Points)."""
    resp = client.put(f"/api/v1/orgs/{org_id}/modules/{module_key}", json={"enabled": True}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def create_pain_point(client, token, project_id, title="Slow reports") -> dict:
    """A Pain Point through Context & Strategy (enable that module before creating the project's data)."""
    base = f"/api/v1/projects/{project_id}/modules/context_strategy"
    types = client.get(f"{base}/pain-point-types", headers=auth_headers(token)).json()
    resp = client.post(
        f"{base}/pain-points", json={"pain_point_type_id": types[0]["id"], "title": title, "description": "Late."},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def create_core_requirement(client, token, project_id, name="Export the list") -> dict:
    """A core requirement in the project (with a fresh component and category if it has none)."""
    from tests.conftest import create_component_and_category

    components = client.get(f"/api/v1/projects/{project_id}/components", headers=auth_headers(token)).json()
    categories = client.get(f"/api/v1/projects/{project_id}/categories", headers=auth_headers(token)).json()
    if components and categories:
        component_id, category_id = components[0]["id"], categories[0]["id"]
    else:
        component_id, category_id = create_component_and_category(client, token, project_id)
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def mark_requirement_completed(requirement_id) -> None:
    """Sets the completion overlay directly (the real route needs an approved requirement and a second person)."""
    from app.database import SessionLocal
    from app.models.requirement import Requirement

    with SessionLocal() as db:
        requirement = db.get(Requirement, uuid.UUID(str(requirement_id)))
        assert requirement is not None
        requirement.is_completed = True
        db.commit()


def add_link(client, token, org_id, project_id, request_id, forward_name, other_type, other_id):
    """POSTs the generic link endpoint from the request's page, with the organisation's link type of that name."""
    rows = client.get(f"/api/v1/orgs/{org_id}/link-types", headers=auth_headers(token)).json()
    link_type = next(row["id"] for row in rows if row["forward_name"] == forward_name)
    return client.post(
        f"/api/v1/projects/{project_id}/artefacts/enhancement_request/{request_id}/links",
        json={"link_type_id": link_type, "direction": "outgoing", "other_type": other_type, "other_id": other_id},
        headers=auth_headers(token),
    )


def get_loop(client, token, project_id, request_id) -> dict:
    resp = client.get(f"{project_base(project_id)}/requests/{request_id}/close-the-loop", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def mark_informed(client, token, project_id, request_id, parties, *, informed=True, note=""):
    """PUTs the informed endpoint; `parties` is a list of `(artefact_type, id)`."""
    return client.put(
        f"{project_base(project_id)}/requests/{request_id}/informed",
        json={"parties": [{"artefact_type": t, "id": i} for t, i in parties], "informed": informed, "note": note},
        headers=auth_headers(token),
    )
