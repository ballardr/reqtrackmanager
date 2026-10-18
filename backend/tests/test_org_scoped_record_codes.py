"""Tests for the human-readable codes of the six types that exist at both organisation and project
scope: Persona (PER), Stakeholder (STK), Stakeholder Group (SGP), Strategy (STR), Future State (FUT)
and Guiding Principle (GP).

Pins: the code on create at each scope; independent numbering per owner (each project, and the
organisation, starts at 001); a code never reused after archive or delete; the code in the summary
label the link finder reads; lookup by qualified code, an organisation-owned record being qualified
by the organisation's code; the organisation-code edit rules; cross-organisation isolation; and the
real migrations numbering existing rows in creation order for both scopes.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy import text as sql_text
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.sequence import OrganizationSequenceCounter
from app.modules.registry import get_artefact_summaries_in_project, list_organization_artefact_summaries
from app.modules.stakeholders.tests.test_persona_api import _create_org_persona, _create_project_persona
from app.modules.stakeholders.tests.test_stakeholder_api import _create_org_stakeholder, _create_project_stakeholder
from app.services.sequences import generate_unique_code
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login


def _enable(client, token, org_id, module_key) -> None:
    resp = client.put(f"/api/v1/orgs/{org_id}/modules/{module_key}", json={"enabled": True}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def _setup(client, admin_token, org_name):
    """An organisation with a real admin and both modules the six types live in."""
    org, token = create_org_admin_in(client, admin_token, org_name)
    for key in ("context_strategy", "stakeholders"):
        _enable(client, token, org["id"], key)
    return org, token


def _post(client, token, url, payload) -> dict:
    resp = client.post(url, json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _cs(scope_url: str) -> str:
    return f"{scope_url}/modules/context_strategy"


def _st(scope_url: str) -> str:
    return f"{scope_url}/modules/stakeholders"


def _persona(client, token, scope_url, name="Field tech") -> dict:
    owner_id = scope_url.rsplit("/", 1)[1]
    create = _create_org_persona if "/orgs/" in scope_url else _create_project_persona
    return create(client, token, owner_id, name=name)


def _stakeholder(client, token, scope_url, name="Pat") -> dict:
    owner_id = scope_url.rsplit("/", 1)[1]
    create = _create_org_stakeholder if "/orgs/" in scope_url else _create_project_stakeholder
    return create(client, token, owner_id, name=name)


def _group(client, token, scope_url, name=None) -> dict:
    return _post(client, token, _st(scope_url) + "/stakeholder-groups", {"name": name or f"Group {uuid.uuid4().hex[:8]}"})


def _strategy(client, token, scope_url, name="Lead") -> dict:
    return _post(client, token, _cs(scope_url) + "/strategies", {"title": name, "objective": "Win"})


def _future_state(client, token, scope_url, name="Automated") -> dict:
    return _post(client, token, _cs(scope_url) + "/future-states", {"title": name})


def _principle(client, token, scope_url, name="Safety first") -> dict:
    return _post(
        client, token, _cs(scope_url) + "/guiding-principles", {"name": name, "principle_statement": "Never compromise."}
    )


_CREATORS = {
    "persona": (_persona, "PER"),
    "stakeholder": (_stakeholder, "STK"),
    "stakeholder_group": (_group, "SGP"),
    "strategy": (_strategy, "STR"),
    "future_state": (_future_state, "FUT"),
    "guiding_principle": (_principle, "GP"),
}


def _scopes(org, project) -> tuple[str, str]:
    return f"/api/v1/orgs/{org['id']}", f"/api/v1/projects/{project['id']}"


def test_each_scope_numbers_independently_from_one(client, admin_token):
    org, token = _setup(client, admin_token, "Codes P8 Numbering Co")
    first = create_project(client, token, org["id"], "P8 First")
    second = create_project(client, token, org["id"], "P8 Second")
    org_url, first_url = _scopes(org, first)
    second_url = f"/api/v1/projects/{second['id']}"
    for key, (create, prefix) in _CREATORS.items():
        a, b = create(client, token, org_url), create(client, token, org_url)
        assert (a["unique_code"], b["unique_code"]) == (f"{prefix}-001", f"{prefix}-002"), key
        assert create(client, token, first_url)["unique_code"] == f"{prefix}-001", key
        assert create(client, token, second_url)["unique_code"] == f"{prefix}-001", key
        assert create(client, token, first_url)["unique_code"] == f"{prefix}-002", key


def test_a_second_organisation_starts_again_at_one(client, admin_token):
    org_a, token_a = _setup(client, admin_token, "Codes P8 Iso A Co")
    org_b, token_b = _setup(client, admin_token, "Codes P8 Iso B Co")
    for key, (create, prefix) in _CREATORS.items():
        assert create(client, token_a, f"/api/v1/orgs/{org_a['id']}")["unique_code"] == f"{prefix}-001", key
        assert create(client, token_b, f"/api/v1/orgs/{org_b['id']}")["unique_code"] == f"{prefix}-001", key


def test_a_code_is_never_reused_after_archive_or_delete(client, admin_token):
    org, token = _setup(client, admin_token, "Codes P8 Reuse Co")
    org_url = f"/api/v1/orgs/{org['id']}"
    h = auth_headers(token)
    created = {key: create(client, token, org_url) for key, (create, _p) in _CREATORS.items()}
    archivable = {
        "persona": _st(org_url) + "/personas", "stakeholder": _st(org_url) + "/stakeholders",
        "strategy": _cs(org_url) + "/strategies", "future_state": _cs(org_url) + "/future-states",
        "guiding_principle": _cs(org_url) + "/guiding-principles",
    }
    for key, base in archivable.items():
        assert client.post(f"{base}/{created[key]['id']}/archive", headers=h).status_code == 200, key
    group_id = created["stakeholder_group"]["id"]
    assert client.delete(_st(org_url) + f"/stakeholder-groups/{group_id}", headers=h).status_code == 204
    for key, (create, prefix) in _CREATORS.items():
        assert create(client, token, org_url)["unique_code"] == f"{prefix}-002", key


def test_an_edit_keeps_the_code(client, admin_token):
    org, token = _setup(client, admin_token, "Codes P8 Edit Co")
    org_url = f"/api/v1/orgs/{org['id']}"
    strategy = _strategy(client, token, org_url)
    resp = client.put(
        _cs(org_url) + f"/strategies/{strategy['id']}",
        json={"title": "Renamed", "objective": "Win", "priority": "high", "time_horizon": "long_term"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["unique_code"] == strategy["unique_code"] == "STR-001"


def test_the_summary_label_leads_with_the_code_at_both_scopes(client, admin_token):
    org, token = _setup(client, admin_token, "Codes P8 Label Co")
    project = create_project(client, token, org["id"], "P8 Label")
    org_url, project_url = _scopes(org, project)
    with SessionLocal() as db:
        for key, (create, prefix) in _CREATORS.items():
            mine = create(client, token, project_url)
            summaries = get_artefact_summaries_in_project(db, uuid.UUID(project["id"]), key, [uuid.UUID(mine["id"])])
            assert summaries[uuid.UUID(mine["id"])].label.startswith(f"{prefix}-001 "), key
            owned = create(client, token, org_url)
            by_org = {s.id: s for s in list_organization_artefact_summaries(db, uuid.UUID(org["id"]), key)}
            assert by_org[uuid.UUID(owned["id"])].label.startswith(f"{prefix}-001 "), key
            assert by_org[uuid.UUID(owned["id"])].organization_id == uuid.UUID(org["id"]), key
            assert uuid.UUID(mine["id"]) not in by_org, key


def test_every_type_is_found_by_its_qualified_code_at_both_scopes(client, admin_token):
    org, token = _setup(client, admin_token, "Codes P8 Lookup Co")
    project = create_project(client, token, org["id"], "P8 Lookup")
    org_url, project_url = _scopes(org, project)
    h = auth_headers(token)
    for key, (create, _prefix) in _CREATORS.items():
        mine, owned = create(client, token, project_url), create(client, token, org_url)
        by_project = client.get(
            f"/api/v1/orgs/{org['id']}/records/by-code/{project['code']}-{mine['unique_code']}", headers=h
        )
        assert by_project.status_code == 200, (key, by_project.text)
        assert (by_project.json()["artefact_type"], by_project.json()["id"]) == (key, mine["id"]), key
        assert by_project.json()["project_id"] == project["id"], key
        by_org = client.get(f"/api/v1/orgs/{org['id']}/records/by-code/{org['code']}-{owned['unique_code']}", headers=h)
        assert by_org.status_code == 200, (key, by_org.text)
        body = by_org.json()
        assert (body["artefact_type"], body["id"], body["project_id"]) == (key, owned["id"], None), key
        assert body["qualified_code"] == f"{org['code']}-{owned['unique_code']}", key
        assert body["label"].startswith(owned["unique_code"]), key


def test_the_organisation_code_does_not_find_a_project_record_and_the_reverse(client, admin_token):
    org, token = _setup(client, admin_token, "Codes P8 Mixup Co")
    project = create_project(client, token, org["id"], "P8 Mixup")
    org_url, project_url = _scopes(org, project)
    h = auth_headers(token)
    owned = _persona(client, token, org_url)
    only_mine = _strategy(client, token, project_url)
    # The same bare code exists in both scopes; each qualifier reaches only its own.
    assert owned["unique_code"] == "PER-001"
    assert client.get(f"/api/v1/orgs/{org['id']}/records/by-code/{project['code']}-PER-001", headers=h).status_code == 404
    assert client.get(f"/api/v1/orgs/{org['id']}/records/by-code/{org['code']}-{only_mine['unique_code']}", headers=h).status_code == 404


def test_another_organisation_cannot_resolve_a_code(client, admin_token):
    org_a, token_a = _setup(client, admin_token, "Codes P8 Cross A Co")
    org_b, token_b = _setup(client, admin_token, "Codes P8 Cross B Co")
    owned = _persona(client, token_a, f"/api/v1/orgs/{org_a['id']}")
    qualified = f"{org_a['code']}-{owned['unique_code']}"
    assert client.get(f"/api/v1/orgs/{org_a['id']}/records/by-code/{qualified}", headers=auth_headers(token_a)).status_code == 200
    # Another organisation's admin has no access to the path, and its own lookup of the same text finds nothing.
    assert client.get(f"/api/v1/orgs/{org_a['id']}/records/by-code/{qualified}", headers=auth_headers(token_b)).status_code == 403
    own_lookup = client.get(f"/api/v1/orgs/{org_b['id']}/records/by-code/{qualified}", headers=auth_headers(token_b))
    assert own_lookup.status_code == 404 or own_lookup.json()["id"] != owned["id"]


def test_an_organisation_record_is_not_found_when_its_module_is_disabled(client, admin_token):
    org, token = _setup(client, admin_token, "Codes P8 Disabled Co")
    owned = _persona(client, token, f"/api/v1/orgs/{org['id']}")
    url = f"/api/v1/orgs/{org['id']}/records/by-code/{org['code']}-{owned['unique_code']}"
    assert client.get(url, headers=auth_headers(token)).status_code == 200
    resp = client.put(f"/api/v1/orgs/{org['id']}/modules/stakeholders", json={"enabled": False}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert client.get(url, headers=auth_headers(token)).status_code == 404


def test_the_link_graph_node_of_an_organisation_record_carries_the_organisation_code(client, admin_token):
    org, token = _setup(client, admin_token, "Codes P8 Graph Co")
    project = create_project(client, token, org["id"], "P8 Graph")
    mine = _persona(client, token, f"/api/v1/projects/{project['id']}")
    owned = _persona(client, token, f"/api/v1/orgs/{org['id']}", "Shared")
    h = auth_headers(token)
    from app.services import relationships

    user_id = uuid.UUID(client.get("/api/v1/auth/me", headers=h).json()["id"])
    with SessionLocal() as db:
        relationships.create_link(
            db, source_type="persona", source_id=uuid.UUID(mine["id"]), target_type="persona",
            target_id=uuid.UUID(owned["id"]), link_type_id=None, created_by=user_id,
        )
        db.commit()
    graph = client.get(f"/api/v1/projects/{project['id']}/artefacts/persona/{mine['id']}/link-graph", headers=h).json()
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert nodes[owned["id"]]["organization_code"] == org["code"] and nodes[owned["id"]]["project_id"] is None
    assert nodes[mine["id"]]["organization_code"] is None and nodes[mine["id"]]["project_code"] == project["code"]


def test_change_the_organisation_code(client, admin_token):
    org, token = _setup(client, admin_token, "Codes P8 Rename Co")
    project = create_project(client, token, org["id"], "P8 Rename")
    owned = _persona(client, token, f"/api/v1/orgs/{org['id']}")
    h = auth_headers(token)
    old_code = org["code"]

    resp = client.put(f"/api/v1/orgs/{org['id']}/code", json={"code": " zulu9 "}, headers=h)
    assert resp.status_code == 200, resp.text
    assert resp.json()["code"] == "ZULU9"
    # The stored record code is untouched; only the qualifier changed, so the old qualified code stops matching.
    assert client.get(f"/api/v1/orgs/{org['id']}/records/by-code/ZULU9-PER-001", headers=h).json()["id"] == owned["id"]
    assert client.get(f"/api/v1/orgs/{org['id']}/records/by-code/{old_code}-PER-001", headers=h).status_code == 404
    with SessionLocal() as db:
        event = db.scalars(
            select(AuditEvent).where(AuditEvent.entity_id == org["id"], AuditEvent.action == "code_updated")
        ).one()
        assert event.detail["previous"] == old_code and event.detail["code"] == "ZULU9"
        # An unchanged code is not an event.
    assert client.put(f"/api/v1/orgs/{org['id']}/code", json={"code": "ZULU9"}, headers=h).status_code == 200
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(
            AuditEvent.entity_id == org["id"], AuditEvent.action == "code_updated"
        )).all()
        assert len(events) == 1
    assert client.get(f"/api/v1/orgs/{org['id']}", headers=h).json()["code"] == "ZULU9"
    assert project["code"] != "ZULU9"


@pytest.mark.parametrize("bad", ["AB-C", "A B", "AB_C", "AB.C", "ABCDEFGHIJKLMNOPQRSTUVWXYZ"])
def test_the_organisation_code_rejects_unusable_values(client, admin_token, bad):
    org, token = _setup(client, admin_token, f"Codes P8 Bad {uuid.uuid4().hex[:6]} Co")
    resp = client.put(f"/api/v1/orgs/{org['id']}/code", json={"code": bad}, headers=auth_headers(token))
    assert resp.status_code in (400, 422), resp.text
    assert client.get(f"/api/v1/orgs/{org['id']}", headers=auth_headers(token)).json()["code"] == org["code"]


def test_the_organisation_code_cannot_equal_a_project_code(client, admin_token):
    org, token = _setup(client, admin_token, "Codes P8 Clash Co")
    project = create_project(client, token, org["id"], "P8 Clash")
    resp = client.put(
        f"/api/v1/orgs/{org['id']}/code", json={"code": project["code"].lower()}, headers=auth_headers(token)
    )
    assert resp.status_code == 409, resp.text


def test_only_an_organisation_admin_can_change_the_organisation_code(client, admin_token):
    org, token = _setup(client, admin_token, "Codes P8 Role Co")
    create_org_user(client, token, org["id"], "p8-plain@example.com")
    plain = login(client, "p8-plain@example.com", "Password123!")
    resp = client.put(f"/api/v1/orgs/{org['id']}/code", json={"code": "NEWC"}, headers=auth_headers(plain))
    assert resp.status_code == 403, resp.text


def test_the_database_refuses_a_duplicate_code_within_one_owner(client, admin_token):
    org, token = _setup(client, admin_token, "Codes P8 Unique Co")
    project = create_project(client, token, org["id"], "P8 Unique")
    owned = _persona(client, token, f"/api/v1/orgs/{org['id']}")
    mine = _persona(client, token, f"/api/v1/projects/{project['id']}")
    with SessionLocal() as db, pytest.raises(IntegrityError):
        db.execute(sql_text(
            "INSERT INTO personas (id, created_at, updated_at, scope, organization_id, unique_code, creator_id, is_archived) "
            "SELECT gen_random_uuid(), now(), now(), 'organization', organization_id, unique_code, creator_id, false "
            "FROM personas WHERE id = :i"
        ), {"i": owned["id"]})
        db.flush()
    # The same bare code in the organisation and in a project is fine: that is the whole point.
    assert owned["unique_code"] == mine["unique_code"] == "PER-001"


def test_the_generator_numbers_an_organisation_from_its_own_counter(client, admin_token):
    from app.models.organization import Organization

    org, _token = _setup(client, admin_token, "Codes P8 Generator Co")
    with SessionLocal() as db:
        row = db.get(Organization, uuid.UUID(org["id"]))
        assert generate_unique_code(db, row, "persona", "PER") == "PER-001"
        assert generate_unique_code(db, row, "persona", "PER") == "PER-002"
        assert generate_unique_code(db, row, "strategy", "STR") == "STR-001"
        counter = db.scalar(select(OrganizationSequenceCounter).where(
            OrganizationSequenceCounter.organization_id == row.id, OrganizationSequenceCounter.artefact_type == "persona"
        ))
        assert counter is not None and counter.next_seq == 3
        with pytest.raises(ValueError):
            generate_unique_code(db, row, "not_a_type", "XX")
        db.rollback()


def test_migrations_number_existing_rows_per_owner_in_creation_order_and_move_the_counters(client, admin_token):
    """Runs the real 0097-0099 migrations: rows created before codes existed are numbered per project and per
    organisation in the order they were created, and each owner's counter continues after them."""
    from alembic import command
    from app.database import engine
    from tests.conftest import build_alembic_config

    org, token = _setup(client, admin_token, "Codes P8 Migration Co")
    project = create_project(client, token, org["id"], "P8 Migration")
    org_url, project_url = _scopes(org, project)
    for create, _prefix in _CREATORS.values():
        for url in (org_url, project_url):
            create(client, token, url)
            create(client, token, url)
    command.downgrade(build_alembic_config(), "0096")
    try:
        with engine.begin() as conn:
            assert conn.execute(sql_text(
                "SELECT count(*) FROM information_schema.columns WHERE column_name = 'unique_code' AND table_name IN "
                "('personas', 'stakeholders', 'stakeholder_groups', 'strategies', 'future_states', 'guiding_principles')"
            )).scalar() == 0
            assert conn.execute(sql_text("SELECT to_regclass('organization_sequence_counters')")).scalar() is None
    finally:
        command.upgrade(build_alembic_config(), "head")
    with engine.begin() as conn:
        for table, prefix in (
            ("personas", "PER"), ("stakeholders", "STK"), ("stakeholder_groups", "SGP"),
            ("strategies", "STR"), ("future_states", "FUT"), ("guiding_principles", "GP"),
        ):
            for column, owner in (("organization_id", org["id"]), ("project_id", project["id"])):
                codes = [r[0] for r in conn.execute(
                    sql_text(f"SELECT unique_code FROM {table} WHERE {column} = :o ORDER BY created_at, id"), {"o": owner}
                )]
                assert codes == [f"{prefix}-001", f"{prefix}-002"], (table, column)
    for key, (create, prefix) in _CREATORS.items():
        assert create(client, token, org_url)["unique_code"] == f"{prefix}-003", key
        assert create(client, token, project_url)["unique_code"] == f"{prefix}-003", key
