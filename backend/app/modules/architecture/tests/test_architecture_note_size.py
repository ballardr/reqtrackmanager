"""Tests for the size mode of an annotation note: the layout save stores and returns it (Manual by default, so a caller that sends a
size keeps it, and a change of mode alone is a change), the schema refuses an unknown mode, the server SVG draws an Automatic note
in the frame its content needs (a leader of a note with no tone starts `NOTE_PADDING` from its text) and a Manual note at its
stored size, the project bundle round trip carries the mode (an older bundle gets the mode an upgrade gives) and the migration
sets existing notes with no tone to Automatic and leaves the rest Manual. Every test builds its own organisation."""

from __future__ import annotations

import io
import json
import re
import zipfile
from typing import Any

from sqlalchemy import text

from alembic import command
from app.database import engine
from app.modules.architecture.diagram_note_layout import NOTE_CAPTION_HEIGHT, automatic_frame
from app.modules.architecture.labels import NOTE_SIZE_MODE_LABEL
from app.modules.architecture.tests._helpers import make_diagram, make_element, place_all, project_base, setup, view
from tests.conftest import auth_headers, build_alembic_config


def _diagram(client, token, project_id):
    a = make_element(client, token, project_id, "Alpha")
    diagram = place_all(client, token, project_id, make_diagram(client, token, project_id, "Size"), a["id"])
    return diagram, [{"element_id": a["id"], "x": 0, "y": 0}], a


def _save(client, token, project_id, diagram, boxes, notes, *, expect=200):
    resp = client.put(
        f"{project_base(project_id)}/diagrams/{diagram['id']}/layout",
        json={"version": diagram["version"], "placements": boxes, "notes": notes}, headers=auth_headers(token),
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def _svg(client, token, project_id, diagram_id) -> str:
    return client.get(f"{project_base(project_id)}/diagrams/{diagram_id}/svg", headers=auth_headers(token)).text


def test_the_size_mode_is_stored_returned_manual_by_default_and_a_change_of_mode_alone_is_a_change(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch note size store")
    p = project["id"]
    diagram, boxes, _a = _diagram(client, token, p)
    notes: list[dict[str, Any]] = [{"text": "Sent a size", "width": 200, "height": 90}, {"text": "Fits", "size_mode": "automatic"}]
    saved = _save(client, token, p, diagram, boxes, notes)
    shown = view(client, token, p, diagram["id"])["notes"]
    assert [(n["size_mode"], n["width"], n["height"]) for n in shown] == [("manual", 200, 90), ("automatic", 160, 60)]
    # The stored size is kept under Automatic (it is what Manual returns to), and the same notes save as no change.
    same = [{**n, "id": s["id"]} for n, s in zip(notes, shown, strict=True)]
    again = _save(client, token, p, saved, boxes, same)
    assert again["version"] == saved["version"]
    same[0]["size_mode"] = "automatic"
    changed = _save(client, token, p, again, boxes, same)
    assert changed["version"] > again["version"]
    assert [(n["size_mode"], n["width"], n["height"]) for n in view(client, token, p, diagram["id"])["notes"]] == [
        ("automatic", 200, 90), ("automatic", 160, 60),
    ]


def test_the_schema_refuses_an_unknown_size_mode(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch note size limits")
    p = project["id"]
    diagram, boxes, _a = _diagram(client, token, p)
    _save(client, token, p, diagram, boxes, [{"size_mode": "fit"}], expect=422)
    assert set(NOTE_SIZE_MODE_LABEL) == {"automatic", "manual"}


def test_an_automatic_note_is_drawn_in_its_content_frame_and_a_manual_one_at_its_stored_size(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch note size svg")
    p = project["id"]
    diagram, boxes, a = _diagram(client, token, p)
    leader = {"kind": "element", "element_id": a["id"], "start_point": "right"}
    _save(client, token, p, diagram, boxes, [
        {"text": "Hi", "tone": "none", "x": 0, "y": 200, "size_mode": "automatic", "leaders": [leader]},
        {"text": "Hi", "tone": "none", "x": 400, "y": 200, "size_mode": "manual", "leaders": [leader]},
        {"text": "Hi", "tone": "neutral", "x": 800, "y": 200, "size_mode": "automatic"},
        {"text": "Hi", "tone": "neutral", "x": 1200, "y": 200, "size_mode": "manual"},
    ])
    svg = _svg(client, token, p, diagram["id"])
    frame = automatic_frame("", "Hi", False)
    assert frame is not None
    width, height = frame
    # The leader of a note with no tone starts at the right edge of the frame, the padding from the words, not 160 units away.
    assert f'x1="{width:.1f}" y1="{200 + height / 2:.1f}"' in svg
    assert 'x1="560.0" y1="230.0"' in svg  # the Manual note: 400 + 160, 200 + 60 / 2
    captioned = automatic_frame("", "Hi", True)
    assert captioned is not None and captioned[1] == height + NOTE_CAPTION_HEIGHT
    assert f'<rect x="800.0" y="200.0" width="{captioned[0]:.1f}" height="{captioned[1]:.1f}"' in svg
    assert '<rect x="1200.0" y="200.0" width="160.0" height="60.0"' in svg
    # The text sits the padding from the frame's left edge and the drawing is large enough to hold it.
    assert re.search(r'<text x="806.0" y="218.0"', svg)


def test_an_empty_automatic_note_keeps_its_stored_size(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch note size empty")
    p = project["id"]
    diagram, boxes, _a = _diagram(client, token, p)
    _save(client, token, p, diagram, boxes, [{"tone": "info", "x": 0, "y": 200, "width": 120, "height": 70, "size_mode": "automatic"}])
    note = view(client, token, p, diagram["id"])["notes"][0]
    assert (note["width"], note["height"]) == (120, 70)  # the stored size is what the editor draws for the placeholder


def test_the_size_mode_round_trips_through_the_project_bundle_and_an_older_bundle_gets_the_upgrade_rule(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch note size bundle")
    p = project["id"]
    diagram, boxes, _a = _diagram(client, token, p)
    _save(client, token, p, diagram, boxes, [
        {"text": "a", "tone": "neutral", "size_mode": "automatic", "x": 0, "y": 200},
        {"text": "b", "tone": "none", "size_mode": "manual", "x": 300, "y": 200},
        {"text": "c", "tone": "none", "x": 600, "y": 200},
        {"text": "d", "tone": "warning", "x": 900, "y": 200},
        {"text": "e", "tone": "warning", "x": 1200, "y": 200},
    ])
    exported = client.get(f"/api/v1/projects/{p}/export", headers=auth_headers(token))
    archive = zipfile.ZipFile(io.BytesIO(exported.content))
    data = json.loads(archive.read("project.json"))
    entries = data["architecture_diagrams"][0]["notes"]
    assert [e["size_mode"] for e in entries] == ["automatic", "manual", "manual", "manual", "manual"]
    # An older bundle has no key; a hand-edited one may have an unknown value.
    entries[2].pop("size_mode")
    entries[3].pop("size_mode")
    entries[4]["size_mode"] = "fit"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as rewritten:
        for item in archive.infolist():
            rewritten.writestr(item, json.dumps(data) if item.filename == "project.json" else archive.read(item.filename))
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch note size bundle copy"},
        files={"file": ("bundle.zip", out.getvalue(), "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    copy = imported.json()["project"]
    listing = client.get(f"{project_base(copy['id'])}/diagrams", headers=auth_headers(token)).json()
    notes = view(client, token, copy["id"], listing[0]["id"])["notes"]
    # With no tone and no key it is Automatic (as an upgrade makes it); a toned note, and an unknown value, stay Manual.
    assert [n["size_mode"] for n in notes] == ["automatic", "manual", "automatic", "manual", "manual"]


def test_the_size_mode_migration_sets_notes_with_no_tone_to_automatic_and_reverses_cleanly(client, admin_token):
    """Upgrading 0195 makes an existing note with no tone Automatic and leaves every other note Manual; downgrading drops the column."""
    _org, project, token = setup(client, admin_token, "Arch note size migration")
    p = project["id"]
    diagram, boxes, _a = _diagram(client, token, p)
    _save(client, token, p, diagram, boxes, [{"text": "plain", "tone": "none"}, {"text": "toned", "tone": "warning", "width": 222}])
    ids = {n["text"]: n["id"] for n in view(client, token, p, diagram["id"])["notes"]}
    command.downgrade(build_alembic_config(), "0194")
    try:
        with engine.connect() as conn:
            columns = {r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'architecture_diagram_notes'"
            ))}
            assert "size_mode" not in columns
    finally:
        command.upgrade(build_alembic_config(), "head")
    with engine.connect() as conn:
        rows = {
            r[0]: (r[1], r[2]) for r in conn.execute(text(
                "SELECT id::text, size_mode, width FROM architecture_diagram_notes WHERE id IN (:a, :b)"
            ), {"a": ids["plain"], "b": ids["toned"]})
        }
        assert rows[ids["plain"]][0] == "automatic"
        assert rows[ids["toned"]] == ("manual", 222.0)  # the stored size is not touched
        assert conn.execute(text(
            "SELECT count(*) FROM pg_constraint WHERE conname = 'ck_architecture_diagram_notes_size_mode'"
        )).scalar_one() == 1
