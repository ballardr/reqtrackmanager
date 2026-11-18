"""Every file the module hands out is audited as one export: the project's JSON and Structurizr files and a diagram's
SVG and Mermaid text (block diagram and state machine diagram). The event carries the record type, the format and a
count, never a name or any drawing text. Every test builds its own organisation.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.architecture.export_audit import PROJECT_FILE_TYPE
from app.modules.architecture.tests._helpers import (
    add_member,
    make_diagram,
    make_element,
    place,
    project_base,
    setup,
    sound_machine,
)
from tests.conftest import auth_headers


def _exports(project_id: str) -> list[AuditEvent]:
    with SessionLocal() as db:
        return list(db.scalars(
            select(AuditEvent).where(AuditEvent.project_id == uuid.UUID(project_id), AuditEvent.action == "records_exported")
            .order_by(AuditEvent.created_at)
        ))


def test_every_file_the_module_downloads_writes_one_export_event(client, admin_token):
    org, project, token = setup(client, admin_token, f"Export audit {uuid.uuid4().hex[:6]}")
    base = project_base(project["id"])
    element = make_element(client, token, project["id"], "Visible box name", activate=True)
    diagram = place(client, token, project["id"], make_diagram(client, token, project["id"], "Visible diagram name"), element["id"], x=0, y=0)
    machine, _states = sound_machine(client, token, project["id"], element["id"], "Visible machine name")
    assert _exports(project["id"]) == []
    downloads = [
        (f"{base}/interchange/json", PROJECT_FILE_TYPE, "json"),
        (f"{base}/interchange/structurizr", PROJECT_FILE_TYPE, "structurizr"),
        (f"{base}/diagrams/{diagram['id']}/svg", "architecture_diagram", "svg"),
        (f"{base}/diagrams/{diagram['id']}/mermaid", "architecture_diagram", "mermaid"),
        (f"{base}/state-machine-diagrams/{machine['id']}/svg", "architecture_state_machine_diagram", "svg"),
        (f"{base}/state-machine-diagrams/{machine['id']}/mermaid", "architecture_state_machine_diagram", "mermaid"),
    ]
    for url, _type, _fmt in downloads:
        resp = client.get(url, headers=auth_headers(token))
        assert resp.status_code == 200, f"{url}: {resp.text[:200]}"
    events = _exports(project["id"])
    details = [e.detail or {} for e in events]
    assert [(d["record_type"], d["format"]) for d in details] == [(t, f) for _u, t, f in downloads]
    assert all(e.actor_id is not None and e.entity_type == "project" for e in events)
    assert details[0]["rows"] >= 3  # the element, the diagram and the state machine diagram
    text = json.dumps(details)
    assert "Visible" not in text, "an export event must carry counts only"


def test_a_download_that_is_refused_writes_no_event(client, admin_token):
    org, project, token = setup(client, admin_token, f"Export refused {uuid.uuid4().hex[:6]}")
    _id, outsider = add_member(client, token, org["id"], create_other(client, token, org), f"x.{uuid.uuid4().hex[:6]}@example.com")
    base = project_base(project["id"])
    for url in (f"{base}/interchange/json", f"{base}/interchange/structurizr", f"{base}/diagrams/{uuid.uuid4()}/svg",
                f"{base}/state-machine-diagrams/{uuid.uuid4()}/mermaid"):
        assert client.get(url, headers=auth_headers(outsider)).status_code in (403, 404)
        assert client.get(url, headers=auth_headers(token)).status_code in (200, 404)
    assert [e for e in _exports(project["id"]) if (e.detail or {}).get("format") in ("svg", "mermaid")] == []


def create_other(client, token, org) -> str:
    """A second project of the organisation (the outsider belongs to it only)."""
    from tests.conftest import create_project

    return create_project(client, token, org["id"], "Other")["id"]
