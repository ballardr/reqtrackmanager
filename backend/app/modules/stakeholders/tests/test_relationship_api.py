"""Tests for the Stakeholders & Personas module's Phase 3 relationships
(docs/plans/module-02-stakeholders-and-personas-plan.md — §10.5), through the
real HTTP endpoints.

Covers: the declared kinds (including the reserved Design/System Element one),
adding/listing/removing each kind from a Stakeholder and a Persona, the
holder/target-type rules, same-project and cross-tenant tenancy, the target
picker, the reverse ("incoming") view, a disabled target module, the FGAC view
filter, RBAC composition, audit logging, erasure of a stakeholder with
relationships, and the MCP tool manifest.

Pain Points and Decisions are real records of their own modules, created
through those modules' own endpoints, so the generic summary-provider hook is
exercised end to end rather than mocked.
"""

from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.relationship import ArtefactLink
from app.modules.stakeholders.tests.test_need_api import _create_requirement
from app.modules.stakeholders.tests.test_persona_api import (
    _add_member,
    _create_org_persona,
    _create_project_persona,
    _grant_project_role,
    _project_base,
    _setup,
)
from app.modules.stakeholders.tests.test_stakeholder_api import _create_org_stakeholder, _create_project_stakeholder
from tests.conftest import auth_headers, create_project


def _enable(client, token, org_id, module_key) -> None:
    resp = client.put(f"/api/v1/orgs/{org_id}/modules/{module_key}", json={"enabled": True}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def _create_pain_point(client, token, org_id, project_id, title="Reports arrive late") -> dict:
    _enable(client, token, org_id, "context_strategy")
    base = f"/api/v1/projects/{project_id}/modules/context_strategy"
    types = client.get(base + "/pain-point-types", headers=auth_headers(token)).json()
    resp = client.post(
        base + "/pain-points",
        json={"title": title, "description": "d", "priority": "high", "date_identified": "2026-09-01",
              "pain_point_type_id": types[0]["id"]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_decision(client, token, org_id, project_id, title="Use Postgres") -> dict:
    _enable(client, token, org_id, "decisions")
    base = f"/api/v1/projects/{project_id}/modules/decisions"
    types = client.get(base + "/decision-types", headers=auth_headers(token)).json()
    resp = client.post(
        base, json={"title": title, "decision_statement": "We will.", "decision_type_id": types[0]["id"]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _rels(project_id, holder_kind, holder_id) -> str:
    return f"{_project_base(project_id)}/{holder_kind}s/{holder_id}/relationships"


def _status(*args) -> int:
    """The status code of `_add(...)`."""
    return _add(*args).status_code


def _add(client, token, project_id, holder_kind, holder_id, kind, target_type, target_id):
    return client.post(
        _rels(project_id, holder_kind, holder_id), json={"kind": kind, "target_type": target_type, "target_id": target_id},
        headers=auth_headers(token),
    )


# --- Kinds -------------------------------------------------------------------


def test_kinds_are_declared_and_design_is_reserved(client, admin_token):
    _, project, token = _setup(client, admin_token, "Rel Kinds Co")
    kinds = {k["key"]: k for k in client.get(f"{_project_base(project['id'])}/relationship-kinds", headers=auth_headers(token)).json()}
    assert set(kinds) == {
        "experiences_pain_point", "provides_requirement", "affected_by_requirement", "consulted_on_decision",
        "approves", "reviews", "uses_design_element",
    }
    assert kinds["provides_requirement"]["available_target_types"] == ["requirement"]
    # Pain Points are available only while their module is installed (it always is) — and the design kind has no target yet.
    assert kinds["uses_design_element"]["available_target_types"] == []
    assert kinds["uses_design_element"]["target_types"] == ["design", "system_element"]
    assert kinds["consulted_on_decision"]["holder_types"] == ["stakeholder"]


def test_reserved_kind_cannot_be_created(client, admin_token):
    _, project, token = _setup(client, admin_token, "Rel Reserved Co")
    stakeholder = _create_project_stakeholder(client, token, project["id"])
    resp = _add(client, token, project["id"], "stakeholder", stakeholder["id"], "uses_design_element", "design", stakeholder["id"])
    assert resp.status_code == 409 and "not available" in resp.json()["detail"]
    assert client.get(_rels(project["id"], "stakeholder", stakeholder["id"]), headers=auth_headers(token)).json() == []


# --- Add / list / remove -----------------------------------------------------


def test_stakeholder_relationships_to_each_target_type(client, admin_token):
    org, project, token = _setup(client, admin_token, "Rel Stakeholder Co")
    h = auth_headers(token)
    stakeholder = _create_project_stakeholder(client, token, project["id"])
    point = _create_pain_point(client, token, org["id"], project["id"])
    decision = _create_decision(client, token, org["id"], project["id"])
    requirement = _create_requirement(client, token, project["id"])
    cases = [
        ("experiences_pain_point", "pain_point", point["id"]),
        ("provides_requirement", "requirement", requirement["id"]),
        ("affected_by_requirement", "requirement", requirement["id"]),
        ("consulted_on_decision", "decision", decision["id"]),
        ("approves", "decision", decision["id"]),
        ("approves", "requirement", requirement["id"]),
        ("reviews", "requirement", requirement["id"]),
    ]
    for kind, target_type, target_id in cases:
        resp = _add(client, token, project["id"], "stakeholder", stakeholder["id"], kind, target_type, target_id)
        assert resp.status_code == 201, (kind, resp.text)
        assert resp.json()["target_id"] == target_id and resp.json()["kind"] == kind
        assert _status(client, token, project["id"], "stakeholder", stakeholder["id"], kind, target_type, target_id) == 409

    listed = client.get(_rels(project["id"], "stakeholder", stakeholder["id"]), headers=h).json()
    assert len(listed) == len(cases)
    by_target = {(r["kind"], r["target_type"]): r for r in listed}
    assert by_target[("experiences_pain_point", "pain_point")]["label"] == point["title"]
    assert by_target[("consulted_on_decision", "decision")]["label"].endswith(decision["title"])
    assert by_target[("provides_requirement", "requirement")]["label"].startswith(requirement["unique_code"])

    link_id = by_target[("reviews", "requirement")]["link_id"]
    assert client.delete(f"{_rels(project['id'], 'stakeholder', stakeholder['id'])}/{link_id}", headers=h).status_code == 204
    assert client.delete(f"{_rels(project['id'], 'stakeholder', stakeholder['id'])}/{link_id}", headers=h).status_code == 404
    assert len(client.get(_rels(project["id"], "stakeholder", stakeholder["id"]), headers=h).json()) == len(cases) - 1


def test_persona_relationships_and_holder_type_rules(client, admin_token):
    org, project, token = _setup(client, admin_token, "Rel Persona Co")
    persona = _create_project_persona(client, token, project["id"])
    point = _create_pain_point(client, token, org["id"], project["id"])
    decision = _create_decision(client, token, org["id"], project["id"])
    requirement = _create_requirement(client, token, project["id"])
    for kind, target_type, target_id in (
        ("experiences_pain_point", "pain_point", point["id"]),
        ("provides_requirement", "requirement", requirement["id"]),
        ("affected_by_requirement", "requirement", requirement["id"]),
    ):
        assert _status(client, token, project["id"], "persona", persona["id"], kind, target_type, target_id) == 201
    # A persona is an archetype: never consulted, never approves, never reviews.
    for kind, target_type, target_id in (
        ("consulted_on_decision", "decision", decision["id"]),
        ("approves", "requirement", requirement["id"]),
        ("reviews", "decision", decision["id"]),
    ):
        resp = _add(client, token, project["id"], "persona", persona["id"], kind, target_type, target_id)
        assert resp.status_code == 409, (kind, resp.text)
    assert len(client.get(_rels(project["id"], "persona", persona["id"]), headers=auth_headers(token)).json()) == 3


def test_target_type_must_match_the_kind_and_kind_must_exist(client, admin_token):
    org, project, token = _setup(client, admin_token, "Rel Mismatch Co")
    stakeholder = _create_project_stakeholder(client, token, project["id"])
    point = _create_pain_point(client, token, org["id"], project["id"])
    assert _status(client, token, project["id"], "stakeholder", stakeholder["id"], "approves", "pain_point", point["id"]) == 409
    assert _status(client, token, project["id"], "stakeholder", stakeholder["id"], "bogus", "pain_point", point["id"]) == 404
    # A real id under the wrong target type is simply not found.
    assert _status(client, token, project["id"], "stakeholder", stakeholder["id"], "provides_requirement", "requirement", point["id"]) == 404


# --- Tenancy -----------------------------------------------------------------


def test_target_must_be_in_the_same_project_and_org(client, admin_token):
    org, project_a, token = _setup(client, admin_token, "Rel Tenancy Co")
    project_b = create_project(client, token, org["id"], "Rel Tenancy B")
    other_org, other_project, other_token = _setup(client, admin_token, "Rel Tenancy Other Co")
    stakeholder = _create_project_stakeholder(client, token, project_a["id"])
    sibling_point = _create_pain_point(client, token, org["id"], project_b["id"])
    foreign_point = _create_pain_point(client, other_token, other_org["id"], other_project["id"])
    sibling_requirement = _create_requirement(client, token, project_b["id"])
    for kind, target_type, target in (
        ("experiences_pain_point", "pain_point", sibling_point["id"]),
        ("experiences_pain_point", "pain_point", foreign_point["id"]),
        ("provides_requirement", "requirement", sibling_requirement["id"]),
    ):
        assert _status(client, token, project_a["id"], "stakeholder", stakeholder["id"], kind, target_type, target) == 404


def test_shared_org_holder_only_shows_this_projects_targets(client, admin_token):
    org, project_a, token = _setup(client, admin_token, "Rel Shared Co")
    project_b = create_project(client, token, org["id"], "Rel Shared B")
    h = auth_headers(token)
    shared = _create_org_stakeholder(client, token, org["id"])
    point_a = _create_pain_point(client, token, org["id"], project_a["id"], "A pain")
    point_b = _create_pain_point(client, token, org["id"], project_b["id"], "B pain")
    for project, point in ((project_a, point_a), (project_b, point_b)):
        assert _status(client, token, project["id"], "stakeholder", shared["id"], "experiences_pain_point", "pain_point", point["id"]) == 201
    assert [r["target_id"] for r in client.get(_rels(project_a["id"], "stakeholder", shared["id"]), headers=h).json()] == [point_a["id"]]
    assert [r["target_id"] for r in client.get(_rels(project_b["id"], "stakeholder", shared["id"]), headers=h).json()] == [point_b["id"]]


def test_holder_must_be_visible_and_link_ids_are_holder_scoped(client, admin_token):
    org, project, token = _setup(client, admin_token, "Rel Holder Co")
    other_org, other_project, other_token = _setup(client, admin_token, "Rel Holder Other Co")
    h = auth_headers(token)
    foreign = _create_project_stakeholder(client, other_token, other_project["id"])
    requirement = _create_requirement(client, token, project["id"])
    assert client.get(_rels(project["id"], "stakeholder", foreign["id"]), headers=h).status_code == 404
    assert _status(client, token, project["id"], "stakeholder", foreign["id"], "provides_requirement", "requirement", requirement["id"]) == 404

    one = _create_project_stakeholder(client, token, project["id"])
    two = _create_project_stakeholder(client, token, project["id"], name="Second")
    link = _add(client, token, project["id"], "stakeholder", one["id"], "provides_requirement", "requirement", requirement["id"]).json()
    # Another holder's id cannot be used to remove a link it does not own.
    assert client.delete(f"{_rels(project['id'], 'stakeholder', two['id'])}/{link['link_id']}", headers=h).status_code == 404
    assert len(client.get(_rels(project["id"], "stakeholder", one["id"]), headers=h).json()) == 1


# --- Picker and reverse view -------------------------------------------------


def test_target_picker_and_incoming_view(client, admin_token):
    org, project, token = _setup(client, admin_token, "Rel Picker Co")
    h = auth_headers(token)
    base = _project_base(project["id"])
    stakeholder = _create_project_stakeholder(client, token, project["id"])
    persona = _create_project_persona(client, token, project["id"])
    point = _create_pain_point(client, token, org["id"], project["id"])
    other_point = _create_pain_point(client, token, org["id"], project["id"], "Another")
    requirement = _create_requirement(client, token, project["id"])

    targets = client.get(f"{base}/relationship-targets?target_type=pain_point", headers=h).json()
    assert {t["id"] for t in targets} == {point["id"], other_point["id"]}
    assert [t["id"] for t in client.get(f"{base}/relationship-targets?target_type=requirement", headers=h).json()] == [requirement["id"]]
    for bad in ("design", "stakeholder_need", "nonsense"):
        assert client.get(f"{base}/relationship-targets?target_type={bad}", headers=h).status_code == 404

    _add(client, token, project["id"], "stakeholder", stakeholder["id"], "experiences_pain_point", "pain_point", point["id"])
    _add(client, token, project["id"], "persona", persona["id"], "experiences_pain_point", "pain_point", point["id"])
    incoming = client.get(f"{base}/relationships/incoming?target_type=pain_point&target_id={point['id']}", headers=h).json()
    assert {(r["holder_type"], r["holder_id"]) for r in incoming} == {("stakeholder", stakeholder["id"]), ("persona", persona["id"])}
    assert {r["reverse"] for r in incoming} == {"Is experienced by"}
    assert client.get(
        f"{base}/relationships/incoming?target_type=pain_point&target_id={other_point['id']}", headers=h
    ).json() == []
    assert client.get(
        f"{base}/relationships/incoming?target_type=pain_point&target_id={stakeholder['id']}", headers=h
    ).status_code == 404


def test_disabled_target_module_hides_and_blocks_its_targets(client, admin_token):
    org, project, token = _setup(client, admin_token, "Rel Disabled Co")
    h = auth_headers(token)
    stakeholder = _create_project_stakeholder(client, token, project["id"])
    point = _create_pain_point(client, token, org["id"], project["id"])
    assert _status(client, token, project["id"], "stakeholder", stakeholder["id"], "experiences_pain_point", "pain_point", point["id"]) == 201
    resp = client.put(f"/api/v1/orgs/{org['id']}/modules/context_strategy", json={"enabled": False}, headers=h)
    assert resp.status_code == 200, resp.text
    assert client.get(_rels(project["id"], "stakeholder", stakeholder["id"]), headers=h).json() == []
    assert _status(client, token, project["id"], "stakeholder", stakeholder["id"], "experiences_pain_point", "pain_point", point["id"]) == 404
    assert client.get(f"{_project_base(project['id'])}/relationship-targets?target_type=pain_point", headers=h).json() == []
    # Re-enabling brings the link back: nothing was deleted.
    _enable(client, token, org["id"], "context_strategy")
    assert len(client.get(_rels(project["id"], "stakeholder", stakeholder["id"]), headers=h).json()) == 1


def test_target_types_the_caller_cannot_view_are_hidden(client, admin_token, monkeypatch):
    org, project, token = _setup(client, admin_token, "Rel Fgac View Co")
    h = auth_headers(token)
    stakeholder = _create_project_stakeholder(client, token, project["id"])
    point = _create_pain_point(client, token, org["id"], project["id"])
    requirement = _create_requirement(client, token, project["id"])
    _add(client, token, project["id"], "stakeholder", stakeholder["id"], "experiences_pain_point", "pain_point", point["id"])
    _add(client, token, project["id"], "stakeholder", stakeholder["id"], "provides_requirement", "requirement", requirement["id"])

    from app.modules.stakeholders import relationship_project_router as router_module

    real = router_module.get_effective_permissions

    def without_pain_point_view(*args, **kwargs):
        return {p for p in real(*args, **kwargs) if not p.startswith("pain_point:view")}

    monkeypatch.setattr(router_module, "get_effective_permissions", without_pain_point_view)
    assert [r["kind"] for r in client.get(_rels(project["id"], "stakeholder", stakeholder["id"]), headers=h).json()] == ["provides_requirement"]
    assert client.get(f"{_project_base(project['id'])}/relationship-targets?target_type=pain_point", headers=h).status_code == 404
    assert _status(client, token, project["id"], "stakeholder", stakeholder["id"], "experiences_pain_point", "pain_point", point["id"]) == 404


# --- RBAC --------------------------------------------------------------------


def test_manage_gate_follows_the_holder_kind(client, admin_token):
    org, project, token = _setup(client, admin_token, "Rel Rbac Co")
    stakeholder = _create_project_stakeholder(client, token, project["id"])
    persona = _create_project_persona(client, token, project["id"])
    requirement = _create_requirement(client, token, project["id"])
    user_id, member = _add_member(client, token, org["id"], project["id"], "rel@rbac.example.com")
    mh = auth_headers(member)

    # A plain member can read but not change.
    assert client.get(_rels(project["id"], "stakeholder", stakeholder["id"]), headers=mh).status_code == 200
    assert client.get(f"{_project_base(project['id'])}/relationship-kinds", headers=mh).status_code == 200
    assert _status(client, member, project["id"], "stakeholder", stakeholder["id"], "provides_requirement", "requirement", requirement["id"]) == 403

    _grant_project_role(client, token, project["id"], user_id, "stakeholder_owner")
    assert _status(client, member, project["id"], "stakeholder", stakeholder["id"], "provides_requirement", "requirement", requirement["id"]) == 201
    # The Stakeholder role confers nothing on Persona relationships, and vice versa.
    assert _status(client, member, project["id"], "persona", persona["id"], "provides_requirement", "requirement", requirement["id"]) == 403
    _grant_project_role(client, token, project["id"], user_id, "persona_owner")
    assert _status(client, member, project["id"], "persona", persona["id"], "provides_requirement", "requirement", requirement["id"]) == 201


def test_disabled_subcomponent_is_404(client, admin_token):
    org, project, token = _setup(client, admin_token, "Rel Subcomponent Co")
    h = auth_headers(token)
    stakeholder = _create_project_stakeholder(client, token, project["id"])
    resp = client.put(f"/api/v1/orgs/{org['id']}/modules/stakeholders/subcomponents/stakeholder", json={"enabled": False}, headers=h)
    assert resp.status_code == 200, resp.text
    assert client.get(_rels(project["id"], "stakeholder", stakeholder["id"]), headers=h).status_code == 404
    # The persona half is unaffected.
    persona = _create_project_persona(client, token, project["id"])
    assert client.get(_rels(project["id"], "persona", persona["id"]), headers=h).status_code == 200


# --- Audit, erasure ----------------------------------------------------------


def test_relationship_changes_are_audit_logged(client, admin_token):
    org, project, token = _setup(client, admin_token, "Rel Audit Co")
    persona = _create_project_persona(client, token, project["id"])
    requirement = _create_requirement(client, token, project["id"])
    link = _add(client, token, project["id"], "persona", persona["id"], "affected_by_requirement", "requirement", requirement["id"]).json()
    client.delete(f"{_rels(project['id'], 'persona', persona['id'])}/{link['link_id']}", headers=auth_headers(token))
    with SessionLocal() as db:
        actions = [
            e.action for e in db.scalars(
                select(AuditEvent).where(AuditEvent.entity_type == "persona", AuditEvent.entity_id == persona["id"])
            ).all()
        ]
    assert "relationship_added" in actions and "relationship_removed" in actions


def test_erasing_a_stakeholder_removes_its_relationships(client, admin_token):
    org, project, token = _setup(client, admin_token, "Rel Erase Co")
    h = auth_headers(token)
    stakeholder = _create_project_stakeholder(client, token, project["id"])
    point = _create_pain_point(client, token, org["id"], project["id"])
    requirement = _create_requirement(client, token, project["id"])
    _add(client, token, project["id"], "stakeholder", stakeholder["id"], "experiences_pain_point", "pain_point", point["id"])
    _add(client, token, project["id"], "stakeholder", stakeholder["id"], "provides_requirement", "requirement", requirement["id"])
    assert client.delete(f"{_project_base(project['id'])}/stakeholders/{stakeholder['id']}", headers=h).status_code == 204
    with SessionLocal() as db:
        remaining = db.scalars(
            select(ArtefactLink).where(
                (ArtefactLink.source_id == stakeholder["id"]) | (ArtefactLink.target_id == stakeholder["id"])
            )
        ).all()
    assert remaining == []
    # The records it pointed at survive.
    assert client.get(f"{_project_base(project['id'])}/relationship-targets?target_type=pain_point", headers=h).json()[0]["id"] == point["id"]


def test_org_stakeholder_relationship_is_managed_by_the_project_gate(client, admin_token):
    """An org-scoped stakeholder's links to *this project's* records are
    project-level data, so the project's own Stakeholder Owner may manage them."""
    org, project, token = _setup(client, admin_token, "Rel Org Holder Co")
    shared = _create_org_stakeholder(client, token, org["id"])
    persona = _create_org_persona(client, token, org["id"])
    requirement = _create_requirement(client, token, project["id"])
    assert _status(client, token, project["id"], "stakeholder", shared["id"], "provides_requirement", "requirement", requirement["id"]) == 201
    assert _status(client, token, project["id"], "persona", persona["id"], "provides_requirement", "requirement", requirement["id"]) == 201


# --- The generic summary-provider hook ---------------------------------------


def test_summary_providers_are_registered_by_their_own_modules_and_gated_by_enablement(client, admin_token):
    from uuid import UUID

    from app.modules.registry import (
        get_artefact_summary,
        has_artefact_summary_provider,
        list_artefact_summaries,
    )

    assert has_artefact_summary_provider("pain_point") and has_artefact_summary_provider("decision")
    assert not has_artefact_summary_provider("design") and not has_artefact_summary_provider("stakeholder")

    org, project, token = _setup(client, admin_token, "Rel Hook Co")
    point = _create_pain_point(client, token, org["id"], project["id"], "Hooked")
    with SessionLocal() as db:
        summary = get_artefact_summary(db, "pain_point", UUID(point["id"]))
        assert summary is not None and summary.label == "Hooked" and summary.project_id == UUID(project["id"])
        assert [s.id for s in list_artefact_summaries(db, UUID(project["id"]), "pain_point")] == [summary.id]
        assert get_artefact_summary(db, "pain_point", UUID(project["id"])) is None  # an id of the wrong kind
        assert get_artefact_summary(db, "design", UUID(point["id"])) is None

    client.put(f"/api/v1/orgs/{org['id']}/modules/context_strategy", json={"enabled": False}, headers=auth_headers(token))
    with SessionLocal() as db:
        assert get_artefact_summary(db, "pain_point", UUID(point["id"])) is None
        assert list_artefact_summaries(db, UUID(project["id"]), "pain_point") == []


def test_stakeholders_module_never_imports_another_modules_package():
    """The module boundary: relationships to other modules' records go through
    the registry's summary providers, never a direct import."""
    from pathlib import Path

    package = Path(__file__).resolve().parents[1]
    offenders = [
        str(path.relative_to(package)) for path in package.rglob("*.py")
        if "tests" not in path.parts
        and any(
            f"app.modules.{other}" in path.read_text()
            for other in ("context_strategy", "decisions", "compliance")
        )
    ]
    assert offenders == []
