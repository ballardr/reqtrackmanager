"""Tests for the human-readable codes of the project-scoped record types that gained one:
pain points (PP), open questions (OQ), stakeholder needs (NEED), compliance evidence (EVD) and
change requests (CR).

Pins, per type: the code on create, numbering per project, a code never reused after the record
is archived or withdrawn, the code in the summary label the link finder and trace read, and
lookup by qualified code. For change requests also: `change_request` is a registered, linkable
artefact type; search by code; a project export/import numbers requests afresh; and the real
migrations number existing rows in creation order and move the counter past them.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy import text as sql_text

from app.database import SessionLocal
from app.modules.registry import get_all_registered_artefact_types
from app.services.sequences import generate_unique_code
from tests.conftest import auth_headers, create_org_admin_in, create_project


def _enable(client, token, org_id, module_key) -> None:
    resp = client.put(f"/api/v1/orgs/{org_id}/modules/{module_key}", json={"enabled": True}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def _setup(client, admin_token, org_name):
    """An organisation with a real admin and every module the five types need enabled."""
    org, token = create_org_admin_in(client, admin_token, org_name)
    for key in ("context_strategy", "stakeholders", "compliance"):
        _enable(client, token, org["id"], key)
    return org, token


def _pain_point(client, token, project_id, title="Reports arrive late") -> dict:
    base = f"/api/v1/projects/{project_id}/modules/context_strategy"
    types = client.get(base + "/pain-point-types", headers=auth_headers(token)).json()
    resp = client.post(
        base + "/pain-points",
        json={"title": title, "priority": "high", "date_identified": "2026-09-01", "pain_point_type_id": types[0]["id"]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _open_question(client, token, project_id, question="Which regions first?") -> dict:
    resp = client.post(
        f"/api/v1/projects/{project_id}/modules/context_strategy/open-questions",
        json={"question": question}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _need(client, token, project_id, name="Diagnose faults quickly") -> dict:
    resp = client.post(
        f"/api/v1/projects/{project_id}/modules/stakeholders/needs", json={"name": name}, headers=auth_headers(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _evidence(client, token, project_id, title="IPX9 Test Certificate") -> dict:
    resp = client.post(
        f"/api/v1/projects/{project_id}/modules/compliance/evidence", json={"title": title}, headers=auth_headers(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _change_request(client, token, project_id, name="Wider doors") -> dict:
    resp = client.post(
        f"/api/v1/projects/{project_id}/change-requests",
        json={"kind": "new_requirement", "proposed_name": name, "reason": "because"}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


_CREATORS = {
    "pain_point": (_pain_point, "PP"),
    "open_question": (_open_question, "OQ"),
    "stakeholder_need": (_need, "NEED"),
    "compliance_evidence": (_evidence, "EVD"),
    "change_request": (_change_request, "CR"),
}


def test_every_type_numbers_per_project_from_one(client, admin_token):
    org, token = _setup(client, admin_token, "Codes P7 Numbering Co")
    first = create_project(client, token, org["id"], "P7 First")
    second = create_project(client, token, org["id"], "P7 Second")
    for key, (create, prefix) in _CREATORS.items():
        a, b = create(client, token, first["id"]), create(client, token, first["id"])
        assert (a["unique_code"], b["unique_code"]) == (f"{prefix}-001", f"{prefix}-002"), key
        assert create(client, token, second["id"])["unique_code"] == f"{prefix}-001", key


def test_a_code_is_never_reused_after_archive_or_withdraw(client, admin_token):
    org, token = _setup(client, admin_token, "Codes P7 Reuse Co")
    project = create_project(client, token, org["id"], "P7 Reuse")
    pid = project["id"]
    h = auth_headers(token)
    base = f"/api/v1/projects/{pid}/modules"
    pain, question = _pain_point(client, token, pid), _open_question(client, token, pid)
    need, evidence, cr = _need(client, token, pid), _evidence(client, token, pid), _change_request(client, token, pid)
    assert client.post(f"{base}/context_strategy/pain-points/{pain['id']}/archive", headers=h).status_code == 200
    assert client.post(f"{base}/context_strategy/open-questions/{question['id']}/archive", headers=h).status_code == 200
    assert client.post(f"{base}/stakeholders/needs/{need['id']}/archive", headers=h).status_code == 200
    assert client.post(f"{base}/compliance/evidence/{evidence['id']}/archive", headers=h).status_code == 200
    assert client.post(f"/api/v1/projects/{pid}/change-requests/{cr['id']}/withdraw", headers=h).status_code == 200
    for key, (create, prefix) in _CREATORS.items():
        assert create(client, token, pid)["unique_code"] == f"{prefix}-002", key


def test_an_edit_keeps_the_code(client, admin_token):
    org, token = _setup(client, admin_token, "Codes P7 Edit Co")
    project = create_project(client, token, org["id"], "P7 Edit")
    pid = project["id"]
    pain = _pain_point(client, token, pid)
    resp = client.put(
        f"/api/v1/projects/{pid}/modules/context_strategy/pain-points/{pain['id']}",
        json={
            "title": "Renamed", "priority": "high", "pain_point_type_id": pain["pain_point_type_id"],
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["unique_code"] == pain["unique_code"] == "PP-001"
    assert client.get(
        f"/api/v1/projects/{pid}/modules/context_strategy/pain-points/{pain['id']}", headers=auth_headers(token)
    ).json()["unique_code"] == "PP-001"


def test_each_type_is_found_by_its_qualified_code(client, admin_token):
    org, token = _setup(client, admin_token, "Codes P7 Lookup Co")
    project = create_project(client, token, org["id"], "P7 Lookup")
    pid = project["id"]
    for key, (create, _prefix) in _CREATORS.items():
        record = create(client, token, pid)
        qualified = f"{project['code']}-{record['unique_code']}"
        resp = client.get(f"/api/v1/orgs/{org['id']}/records/by-code/{qualified}", headers=auth_headers(token))
        assert resp.status_code == 200, (key, resp.text)
        body = resp.json()
        assert (body["artefact_type"], body["id"], body["project_id"]) == (key, record["id"], pid), key
        assert body["label"].startswith(record["unique_code"]), key


def test_the_summary_label_leads_with_the_code(client, admin_token):
    org, token = _setup(client, admin_token, "Codes P7 Label Co")
    project = create_project(client, token, org["id"], "P7 Label")
    pid = project["id"]
    records = {key: create(client, token, pid) for key, (create, _p) in _CREATORS.items()}
    from app.modules.registry import get_artefact_summaries_in_project
    from app.services.change_request_summary import change_request_summaries

    with SessionLocal() as db:
        for key in ("pain_point", "open_question", "stakeholder_need", "compliance_evidence"):
            summaries = get_artefact_summaries_in_project(db, uuid.UUID(pid), key, [uuid.UUID(records[key]["id"])])
            label = summaries[uuid.UUID(records[key]["id"])].label
            assert label.startswith(records[key]["unique_code"] + " "), (key, label)
        cr_id = uuid.UUID(records["change_request"]["id"])
        label = change_request_summaries(db, [uuid.UUID(pid)], [cr_id])[cr_id].label
        assert label == "CR-001 Wider doors"


def test_change_request_is_a_registered_core_type_with_a_label():
    from app.modules.registry import get_artefact_type_label

    assert "change_request" in get_all_registered_artefact_types()
    assert get_artefact_type_label("change_request") == "Change request"


def test_a_change_request_can_be_found_linked_and_shown_with_its_code(client, admin_token):
    org, token = _setup(client, admin_token, "Codes P7 Graph Co")
    project = create_project(client, token, org["id"], "P7 Graph")
    pid = project["id"]
    h = auth_headers(token)
    cr = _change_request(client, token, pid)
    question = _open_question(client, token, pid)
    page = f"/api/v1/projects/{pid}/artefacts/open_question/{question['id']}"
    # The finder offers change requests as a target type, searchable by code and by title.
    for needle in ("cr-001", "wider"):
        found = client.get(f"{page}/link-candidates", params={"other_type": "change_request", "q": needle}, headers=h)
        assert found.status_code == 200, found.text
        assert [(i["type"], i["id"], i["label"]) for i in found.json()["items"]] == [
            ("change_request", cr["id"], "CR-001 Wider doors")
        ]
    # ... and by status, its browse level.
    narrowed = client.get(
        f"{page}/link-candidates", params={"other_type": "change_request", "selected": "status:withdrawn"}, headers=h
    )
    assert narrowed.status_code == 200 and narrowed.json()["items"] == []
    link_types = client.get(f"/api/v1/orgs/{org['id']}/link-types", headers=h).json()
    created = client.post(
        f"{page}/links",
        json={"link_type_id": link_types[0]["id"], "direction": "outgoing", "other_type": "change_request", "other_id": cr["id"]},
        headers=h,
    )
    assert created.status_code == 201, created.text
    graph = client.get(f"{page}/link-graph", params={"depth": 1, "direction": "both"}, headers=h).json()
    assert {n["type"]: n["label"] for n in graph["nodes"]}["change_request"] == "CR-001 Wider doors"


def test_change_request_list_search_matches_the_code(client, admin_token):
    org, token = _setup(client, admin_token, "Codes P7 Search Co")
    project = create_project(client, token, org["id"], "P7 Search")
    pid = project["id"]
    _change_request(client, token, pid, "Alpha")
    second = _change_request(client, token, pid, "Beta")
    resp = client.get(f"/api/v1/projects/{pid}/change-requests", params={"search": "cr-002"}, headers=auth_headers(token))
    assert [c["id"] for c in resp.json()] == [second["id"]]


def test_change_request_notification_title_leads_with_the_code(client, admin_token):
    """The title every change request notification is built from carries the request's code."""
    from app.models.change_request import ChangeRequest, ChangeRequestVersion
    from app.routers.change_requests.workflow import _display_title

    org, token = _setup(client, admin_token, "Codes P7 Notify Co")
    project = create_project(client, token, org["id"], "P7 Notify")
    cr = _change_request(client, token, project["id"], "Wider doors")
    with SessionLocal() as db:
        row = db.get(ChangeRequest, uuid.UUID(cr["id"]))
        version = db.scalars(select(ChangeRequestVersion).where(ChangeRequestVersion.change_request_id == row.id)).one()
        assert _display_title(db, row, version) == "CR-001 Wider doors"


def test_project_export_and_import_number_change_requests_afresh(client, admin_token):
    org, token = _setup(client, admin_token, "Codes P7 Export Co")
    project = create_project(client, token, org["id"], "P7 Export")
    pid = project["id"]
    h = auth_headers(token)
    _change_request(client, token, pid, "First")
    second = _change_request(client, token, pid, "Second")
    assert client.post(f"/api/v1/projects/{pid}/change-requests/{second['id']}/withdraw", headers=h).status_code == 200
    exported = client.get(f"/api/v1/projects/{pid}/export", headers=h)
    assert exported.status_code == 200, exported.text
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "P7 Export Copy"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=h,
    )
    assert imported.status_code == 201, imported.text
    new_id = imported.json()["project"]["id"]
    codes = sorted(c["unique_code"] for c in client.get(f"/api/v1/projects/{new_id}/change-requests", headers=h).json())
    assert codes == ["CR-001", "CR-002"]
    assert _change_request(client, token, new_id, "Third")["unique_code"] == "CR-003"


def test_unregistered_type_is_still_refused_by_the_generator():
    import pytest

    with SessionLocal() as db, pytest.raises(ValueError):
        generate_unique_code(db, None, "not_a_type", "XX")  # type: ignore[arg-type]


def test_migrations_number_existing_rows_in_creation_order_and_move_the_counter(client, admin_token):
    """Runs the real 0093-0096 migrations: rows created before codes existed are numbered per project in
    the order they were created, and the project's counter continues after them."""
    from alembic import command
    from app.database import engine
    from tests.conftest import build_alembic_config

    org, token = _setup(client, admin_token, "Codes P7 Migration Co")
    project = create_project(client, token, org["id"], "P7 Migration")
    pid = project["id"]
    for create, _prefix in _CREATORS.values():
        for _ in range(2):
            create(client, token, pid)
    command.downgrade(build_alembic_config(), "0092")
    try:
        with engine.begin() as conn:
            remaining = conn.execute(sql_text(
                "SELECT count(*) FROM information_schema.columns WHERE column_name = 'unique_code' AND table_name IN "
                "('pain_points', 'open_questions', 'stakeholder_needs', 'compliance_evidence', 'change_requests')"
            )).scalar()
            assert remaining == 0
    finally:
        command.upgrade(build_alembic_config(), "head")
    with engine.begin() as conn:
        for table, prefix in (
            ("pain_points", "PP"), ("open_questions", "OQ"), ("stakeholder_needs", "NEED"),
            ("compliance_evidence", "EVD"), ("change_requests", "CR"),
        ):
            codes = [r[0] for r in conn.execute(
                sql_text(f"SELECT unique_code FROM {table} WHERE project_id = :p ORDER BY created_at, id"), {"p": pid}
            )]
            assert codes == [f"{prefix}-001", f"{prefix}-002"], table
    for key, (create, prefix) in _CREATORS.items():
        assert create(client, token, pid)["unique_code"] == f"{prefix}-003", key
