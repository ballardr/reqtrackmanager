"""Tests for Decisions as Markdown: every text field and the long-form `document` store the author's Markdown source
(a table, a Mermaid diagram), enforce its size, nesting and diagram limits on every write path (the endpoint and a
file import), lock with the rest of the content once approved, are found by the global search (with a snippet that
shows plain text, not marks), travel through the CSV and the project bundle as source, and read as plain text in a
report cell. Each test builds its own organisation, so none depends on state left by another test.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
import zipfile

from sqlalchemy import select

from app.database import SessionLocal
from app.modules.decisions.models import Decision
from app.modules.decisions.tests.test_decisions_api import (
    _advance_to_under_review,
    _approve,
    _base,
    _create_decision,
    _first_decision_type_id,
    _setup,
)
from tests.conftest import auth_headers

DOCUMENT = """## Summary

We **adopt** a queue.

```mermaid
flowchart LR
    A[Producer] --> B[Queue]
```

| Option | Cost |
|---|---|
| Queue | Low |
"""


def _world(client, admin_token, name):
    _, project, token = _setup(client, admin_token, name)
    return project, token, _first_decision_type_id(client, token, project["id"])


def _put(client, token, project, decision: dict, **changes):
    return client.put(
        f"{_base(project['id'])}/{decision['id']}", json={**decision, **changes}, headers=auth_headers(token),
    )


def test_a_decision_stores_its_document_and_text_fields_as_the_source_typed(client, admin_token):
    project, token, type_id = _world(client, admin_token, "Dec Markdown Store Co")
    created = _create_decision(
        client, token, project["id"], type_id, document=DOCUMENT, rationale="Because **it scales**.",
    )
    assert created["document"] == DOCUMENT and created["rationale"] == "Because **it scales**."
    fetched = client.get(f"{_base(project['id'])}/{created['id']}", headers=auth_headers(token)).json()
    assert fetched["document"] == DOCUMENT
    listed = client.get(_base(project["id"]), headers=auth_headers(token)).json()
    assert [d["document"] for d in listed] == [DOCUMENT]

    updated = _put(client, token, project, fetched, document="Replaced.")
    assert updated.status_code == 200, updated.text
    assert updated.json()["document"] == "Replaced."


def test_a_decision_without_a_document_has_none_and_the_edit_may_clear_it(client, admin_token):
    project, token, type_id = _world(client, admin_token, "Dec Markdown None Co")
    created = _create_decision(client, token, project["id"], type_id)
    assert created["document"] is None
    with_document = _put(client, token, project, created, document=DOCUMENT).json()
    assert _put(client, token, project, with_document, document=None).json()["document"] is None


def test_an_approved_decision_refuses_an_edit_of_its_document(client, admin_token):
    project, token, type_id = _world(client, admin_token, "Dec Markdown Lock Co")
    created = _create_decision(client, token, project["id"], type_id, document=DOCUMENT)
    _advance_to_under_review(client, token, project["id"], created["id"])
    approved = _approve(client, token, project["id"], created["id"])
    refused = _put(client, token, project, approved, document="Changed after approval.")
    assert refused.status_code == 409
    after = client.get(f"{_base(project['id'])}/{created['id']}", headers=auth_headers(token)).json()
    assert after["document"] == DOCUMENT


def test_text_over_its_limits_is_a_422_that_names_the_field(client, admin_token):
    project, token, type_id = _world(client, admin_token, "Dec Markdown Limits Co")
    base = {"title": "T", "decision_statement": "S", "decision_type_id": type_id}
    url, headers = _base(project["id"]), auth_headers(token)

    too_long = client.post(url, json={**base, "document": "x" * 200_001}, headers=headers)
    assert too_long.status_code == 422 and "Document" in too_long.json()["detail"]
    field_too_long = client.post(url, json={**base, "rationale": "x" * 50_001}, headers=headers)
    assert field_too_long.status_code == 422 and "Rationale" in field_too_long.json()["detail"]
    many_diagrams = client.post(url, json={**base, "context": "```mermaid\nflowchart LR\nA-->B\n```\n" * 21}, headers=headers)
    assert many_diagrams.status_code == 422 and "diagrams" in many_diagrams.json()["detail"]
    deep = client.post(url, json={**base, "document": "> " * 60 + "deep"}, headers=headers)
    assert deep.status_code == 422 and "nested" in deep.json()["detail"]
    big_diagram = client.post(url, json={**base, "document": "```mermaid\n" + "A-->B\n" * 4000 + "```"}, headers=headers)
    assert big_diagram.status_code == 422
    assert client.get(url, headers=headers).json() == []  # nothing was stored

    ok = client.post(url, json={**base, "document": "x" * 200_000}, headers=headers)
    assert ok.status_code == 201, ok.text


def test_a_limit_also_stops_a_file_import_for_that_row(client, admin_token):
    project, token, type_id = _world(client, admin_token, "Dec Markdown Import Limit Co")
    types = client.get(f"{_base(project['id'])}/decision-types", headers=auth_headers(token)).json()
    name = next(t["name"] for t in types if t["id"] == type_id)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["code", "title", "decision_statement", "type", "document"])
    writer.writerow(["", "Too big", "S", name, "x" * 200_001])
    writer.writerow(["", "Fine", "S", name, DOCUMENT])
    preview = client.post(
        f"/api/v1/projects/{project['id']}/records/decision/import", params={"dry_run": "true"},
        files={"file": ("records.csv", out.getvalue().encode(), "text/csv")}, headers=auth_headers(token),
    )
    assert preview.status_code == 200, preview.text
    preview = preview.json()
    assert (preview["created"], preview["failed"]) == (1, 1), preview


def test_the_csv_carries_the_document_source_and_an_edit_through_it_updates_it(client, admin_token):
    project, token, type_id = _world(client, admin_token, "Dec Markdown Csv Co")
    created = _create_decision(client, token, project["id"], type_id, document=DOCUMENT)
    records = f"/api/v1/projects/{project['id']}/records/decision"
    exported = client.get(f"{records}/export", headers=auth_headers(token))
    rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert rows[0]["document"] == DOCUMENT
    unchanged = client.post(
        f"{records}/import", params={"dry_run": "true"},
        files={"file": ("records.csv", exported.content, "text/csv")}, headers=auth_headers(token),
    ).json()
    assert (unchanged["updated"], unchanged["unchanged"]) == (0, 1), unchanged

    edited = "code,document\n" + created["unique_code"] + ',"Rewritten, with a comma."\n'
    applied = client.post(
        f"{records}/import", params={"dry_run": "false"},
        files={"file": ("records.csv", edited.encode(), "text/csv")}, headers=auth_headers(token),
    ).json()
    assert applied["updated"] == 1, applied
    got = client.get(f"{_base(project['id'])}/{created['id']}", headers=auth_headers(token)).json()
    assert got["document"] == "Rewritten, with a comma."


def test_search_finds_document_text_and_the_snippet_shows_plain_text(client, admin_token):
    project, token, type_id = _world(client, admin_token, "Dec Markdown Search Co")
    decision = _create_decision(
        client, token, project["id"], type_id, document="## Plan\n\nWe **adopt** the quokkazq pattern.\n",
    )
    scope = {"scope": "project", "project_id": project["id"]}

    def search(body):
        resp = client.post("/api/v1/search", json={**body, **scope}, headers=auth_headers(token))
        assert resp.status_code == 200, resp.text
        return resp.json()["hits"]

    assert search({"q": "quokkazq"}) == []  # a long-form field is searched only when selected
    hits = search({"q": "quokkazq", "fields": ["id", "title", "document"]})
    assert [h["id"] for h in hits] == [decision["id"]]
    snippet = hits[0]["snippet"]
    assert snippet["field_label"] == "Document"
    assert "**" not in snippet["text"] and "##" not in snippet["text"] and "quokkazq" in snippet["text"]


def test_diagram_source_is_searchable_and_the_project_bundle_round_trips_the_document(client, admin_token):
    project, token, type_id = _world(client, admin_token, "Dec Markdown Bundle Co")
    org_id = project["organization_id"]
    _create_decision(client, token, project["id"], type_id, document=DOCUMENT, rationale="Plain **rationale**.")
    exported = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(token))
    assert exported.status_code == 200, exported.text
    with zipfile.ZipFile(io.BytesIO(exported.content)) as bundle:
        data = json.loads(bundle.read("project.json"))
    assert data["decisions"][0]["document"] == DOCUMENT

    resp = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": "Dec Markdown Bundle Copy"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    db = SessionLocal()
    try:
        copy = db.scalars(select(Decision).where(Decision.project_id == uuid.UUID(resp.json()["project"]["id"]))).one()
        assert copy.document == DOCUMENT and copy.rationale == "Plain **rationale**."
    finally:
        db.close()
