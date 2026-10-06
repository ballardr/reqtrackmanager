"""Shared fixture builder for link tests: one organisation with an admin and
helpers to create requirements, actions, decisions, link types and links in it.
Each `World` makes its own uniquely named organisation, so tests stay independent."""

from __future__ import annotations

import uuid

from app.database import SessionLocal
from app.models.enums import ArtefactType
from app.modules.decisions.models import Decision, DecisionTypeDefinition
from app.services import relationships
from tests.conftest import auth_headers, create_component_and_category, create_org_admin_in, create_project

REQ = ArtefactType.REQUIREMENT.value
ACTION = ArtefactType.REQUIREMENT_ACTION.value


class World:
    """One organisation with an admin and helpers to build artefacts and links in it."""

    def __init__(
        self, client, admin_token, name: str, *, decisions: bool = False, context_strategy: bool = False
    ) -> None:
        """Creates the organisation and its admin; `decisions`/`context_strategy` switch those modules on."""
        self.client = client
        self.org, self.token = create_org_admin_in(client, admin_token, f"{name} {uuid.uuid4().hex[:6]}")
        if decisions:
            self.enable("decisions")
        if context_strategy:
            self.enable("context_strategy")
        self.user_id = uuid.UUID(client.get("/api/v1/auth/me", headers=auth_headers(self.token)).json()["id"])

    def enable(self, module_key: str) -> None:
        """Turns a module on for the organisation (call before creating projects that need its seeded data)."""
        resp = self.client.put(
            f"/api/v1/orgs/{self.org['id']}/modules/{module_key}", json={"enabled": True},
            headers=auth_headers(self.token),
        )
        assert resp.status_code == 200, resp.text

    def pain_point(self, project: dict, title: str = "Slow reports") -> uuid.UUID:
        """Creates a Pain Point through the Context & Strategy API (module must be enabled)."""
        base = f"/api/v1/projects/{project['id']}/modules/context_strategy"
        types = self.client.get(f"{base}/pain-point-types", headers=auth_headers(self.token)).json()
        resp = self.client.post(
            f"{base}/pain-points",
            json={"pain_point_type_id": types[0]["id"], "title": title, "description": "Reports are late."},
            headers=auth_headers(self.token),
        )
        assert resp.status_code == 201, resp.text
        return uuid.UUID(resp.json()["id"])

    def link_types_by_name(self) -> dict[str, dict]:
        """The organisation's link types as `{forward_name: row}` (module seeds included)."""
        rows = self.client.get(f"/api/v1/orgs/{self.org['id']}/link-types", headers=auth_headers(self.token)).json()
        return {row["forward_name"]: row for row in rows}

    def generic_link(
        self, project: dict, artefact: tuple[str, uuid.UUID], link_type_id, other: tuple[str, uuid.UUID],
        direction: str = "outgoing", token=None,
    ):
        """POSTs the generic link-authoring endpoint from `artefact`'s side."""
        return self.client.post(
            f"/api/v1/projects/{project['id']}/artefacts/{artefact[0]}/{artefact[1]}/links",
            json={
                "link_type_id": str(link_type_id), "direction": direction,
                "other_type": other[0], "other_id": str(other[1]),
            },
            headers=auth_headers(token or self.token),
        )

    def project(self, name: str = "P") -> dict:
        """Creates a project with a component and category (as `component_id`/`category_id`)."""
        project = create_project(self.client, self.token, self.org["id"], name)
        project["component_id"], project["category_id"] = create_component_and_category(
            self.client, self.token, project["id"]
        )
        return project

    def requirement(self, project: dict, name: str = "Req") -> uuid.UUID:
        """Creates a requirement through the API and returns its id."""
        resp = self.client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"name": name, "component_id": project["component_id"], "category_id": project["category_id"]},
            headers=auth_headers(self.token),
        )
        assert resp.status_code == 201, resp.text
        return uuid.UUID(resp.json()["id"])

    def action(self, project: dict, title: str = "Act") -> uuid.UUID:
        """Creates a requirement action through the API and returns its id."""
        types = self.client.get(f"/api/v1/projects/{project['id']}/action-types", headers=auth_headers(self.token)).json()
        resp = self.client.post(
            f"/api/v1/projects/{project['id']}/actions", json={"title": title, "action_type_id": types[0]["id"]},
            headers=auth_headers(self.token),
        )
        assert resp.status_code == 201, resp.text
        return uuid.UUID(resp.json()["id"])

    def decision(self, project: dict, code: str = "DEC-1") -> uuid.UUID:
        """Inserts a Decision directly (needs the Decisions module on) and returns its id."""
        db = SessionLocal()
        try:
            type_id = db.query(DecisionTypeDefinition.id).filter(
                DecisionTypeDefinition.project_id == project["id"]
            ).first()[0]
            decision = Decision(
                project_id=project["id"], unique_code=code, title=f"Decision {code}", decision_statement="S",
                decision_type_id=type_id, owner_id=self.user_id, creator_id=self.user_id,
            )
            db.add(decision)
            db.commit()
            return decision.id
        finally:
            db.close()

    def link_type(self, forward: str, reverse: str, flow: str = "none") -> uuid.UUID:
        """Creates a uniquely named org link type and returns its id."""
        resp = self.client.post(
            f"/api/v1/orgs/{self.org['id']}/link-types",
            json={"forward_name": f"{forward} {uuid.uuid4().hex[:4]}", "reverse_name": reverse, "flow": flow},
            headers=auth_headers(self.token),
        )
        assert resp.status_code == 201, resp.text
        return uuid.UUID(resp.json()["id"])

    def link(self, source: tuple[str, uuid.UUID], target: tuple[str, uuid.UUID], link_type_id=None) -> uuid.UUID:
        """Inserts an `ArtefactLink` directly, bypassing authoring rules, and returns its id."""
        db = SessionLocal()
        try:
            row = relationships.create_link(
                db, source_type=source[0], source_id=source[1], target_type=target[0], target_id=target[1],
                link_type_id=link_type_id, created_by=self.user_id,
            )
            db.commit()
            return row.id
        finally:
            db.close()

    def graph(self, project: dict, artefact: tuple[str, uuid.UUID], token=None, **params):
        """GETs the link graph around `artefact`."""
        return self.client.get(
            f"/api/v1/projects/{project['id']}/artefacts/{artefact[0]}/{artefact[1]}/link-graph", params=params,
            headers=auth_headers(token or self.token),
        )
