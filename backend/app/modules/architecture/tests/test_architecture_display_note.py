"""Tests for an element's display note: the short plain-text line drawn inside its box (never the long description). It is
capped, stored trimmed, audited as a field name only, carried by the diagram's view and model, drawn by the server SVG
(wrapped, clipped, escaped) and the Mermaid export, and found by the search. CSV and bundle round trips are in
`test_architecture_record_tables.py` and `test_architecture_record_bundles.py`. Every test builds its own organisation."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from app.modules.architecture.enums import DISPLAY_NOTE_MAX
from app.modules.architecture.tests._helpers import make_diagram, make_element, place_all, project_base, put_element, setup, view
from tests.conftest import auth_headers

ALL_FIELDS = ["id", "title", "description", "display_note"]


def _svg_texts(svg: str) -> list[str]:
    """The text of every `<text>` element in a server SVG."""
    return ["".join(el.itertext()) for el in ET.fromstring(svg).iter("{http://www.w3.org/2000/svg}text")]


def test_a_note_is_stored_trimmed_and_edited_separately_from_the_description(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch note store")
    element = make_element(
        client, token, project["id"], "Gateway", description="Long text about the gateway.",
        display_note="  Buffers readings.\r\nForwards hourly.  ",
    )
    assert element["display_note"] == "Buffers readings.\nForwards hourly."
    assert element["description"] == "Long text about the gateway."
    edited = put_element(client, token, project["id"], element, display_note="Now a gateway.")
    assert edited["display_note"] == "Now a gateway." and edited["description"] == "Long text about the gateway."
    cleared = put_element(client, token, project["id"], edited, display_note="")
    assert cleared["display_note"] == "" and cleared["version"] > edited["version"]
    unchanged = put_element(client, token, project["id"], cleared, name="Gateway 2")
    assert unchanged["display_note"] == ""


def test_a_note_longer_than_the_cap_is_refused_and_one_at_the_cap_is_kept(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch note cap")
    full = make_element(client, token, project["id"], "Full", display_note="x" * DISPLAY_NOTE_MAX)
    assert len(full["display_note"]) == DISPLAY_NOTE_MAX
    make_element(client, token, project["id"], "Over", display_note="x" * (DISPLAY_NOTE_MAX + 1), expect=422)
    put_element(client, token, project["id"], full, display_note="y" * (DISPLAY_NOTE_MAX + 1), expect=422)


def test_the_audit_names_the_changed_field_and_never_the_note(client, admin_token):
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import AuditEvent

    _org, project, token = setup(client, admin_token, "Arch note audit")
    element = make_element(client, token, project["id"], "Gateway")
    put_element(client, token, project["id"], element, display_note="Secret wording.")
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.entity_id == element["id"]).order_by(AuditEvent.created_at)).all()
    assert events[-1].detail == {"fields": ["display_note"]}
    assert all("Secret wording." not in str(e.detail) for e in events)


def test_the_view_and_the_model_carry_the_note_and_a_shared_locked_box_does_not(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch note view")
    a = make_element(client, token, project["id"], "Gateway", display_note="Buffers readings.")
    b = make_element(client, token, project["id"], "Plain")
    diagram = place_all(client, token, project["id"], make_diagram(client, token, project["id"], "Flow"), a["id"], b["id"])
    nodes = {n["name"]: n for n in view(client, token, project["id"], diagram["id"])["nodes"]}
    assert nodes["Gateway"]["display_note"] == "Buffers readings." and nodes["Plain"]["display_note"] == ""
    resp = client.get(f"{project_base(project['id'])}/diagrams/{diagram['id']}/model", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    notes = {e["name"]: e["display_note"] for e in resp.json()["elements"]}
    assert notes["Gateway"] == "Buffers readings." and notes["Plain"] == ""


def _svg(client, token, project_id, diagram_id) -> str:
    resp = client.get(f"{project_base(project_id)}/diagrams/{diagram_id}/svg", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.text


def test_the_svg_draws_the_note_under_the_name_wrapped_and_escaped(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch note svg")
    element = make_element(client, token, project["id"], "Gateway", display_note="Buffers <b>readings</b> & forwards them")
    diagram = place_all(client, token, project["id"], make_diagram(client, token, project["id"], "Flow"), element["id"])
    svg = _svg(client, token, project["id"], diagram["id"])
    assert "<b>" not in svg
    texts = _svg_texts(svg)
    assert any("<b>readings</b>" in t for t in texts), texts
    assert texts.index("Gateway") < max(i for i, t in enumerate(texts) if "forwards" in t or "readings" in t)


def test_the_svg_clips_a_note_that_does_not_fit_with_an_ellipsis_and_never_the_description(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch note clip")
    long_note = " ".join(f"word{i}" for i in range(60))
    element = make_element(client, token, project["id"], "Gateway", display_note=long_note, description="Never drawn on a diagram.")
    diagram = place_all(client, token, project["id"], make_diagram(client, token, project["id"], "Flow"), element["id"])
    svg = _svg(client, token, project["id"], diagram["id"])
    texts = _svg_texts(svg)
    assert "Never drawn on a diagram." not in svg
    assert "word59" not in svg and any("word" in t and t.endswith("…") for t in texts)
    assert len([t for t in texts if re.match(r"^word\d+", t)]) <= 12


def test_the_svg_of_an_element_with_no_note_is_unchanged_in_shape(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch note none")
    element = make_element(client, token, project["id"], "Gateway")
    diagram = place_all(client, token, project["id"], make_diagram(client, token, project["id"], "Flow"), element["id"])
    texts = _svg_texts(_svg(client, token, project["id"], diagram["id"]))
    assert "Gateway" in texts and "ELM-001" in texts and not [t for t in texts if t.startswith("word")]


def test_mermaid_writes_each_note_line_in_the_node_label(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch note mermaid")
    element = make_element(client, token, project["id"], "Gateway", display_note='Line one\n\nLine "two" <b>')
    diagram = place_all(client, token, project["id"], make_diagram(client, token, project["id"], "Flow"), element["id"])
    resp = client.get(f"{project_base(project['id'])}/diagrams/{diagram['id']}/mermaid", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    node = next(line for line in resp.text.splitlines() if line.startswith("    n1"))
    assert "<br/>Gateway<br/>Line one<br/>Line " in node and "<b>" not in node
    assert re.match(r'^    n1[^"]*"[^"]*"[^"]*$', node)


def test_the_search_finds_an_element_by_its_note_only_when_the_field_is_asked_for(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch note search")
    make_element(client, token, project["id"], "Gateway", display_note="Handles uplinkzebra traffic.")

    def hits(fields):
        resp = client.post(
            "/api/v1/search", json={"q": "uplinkzebra", "scope": "project", "project_id": project["id"], "fields": fields},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200, resp.text
        return [h["title"] for h in resp.json()["hits"] if h["type"] == "architecture_element"]

    assert hits(ALL_FIELDS) == ["Gateway"]
    assert hits(["id", "title"]) == []
