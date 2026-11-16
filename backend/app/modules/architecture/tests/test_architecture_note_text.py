"""Tests for the title, the typed line breaks and the alignment of an annotation note on a diagram: the schema accepts a
120-character title and refuses 121 and an unknown alignment, the layout save stores and returns them (and an unchanged note
saves as no change), the server SVG draws the title in bold above the text with each typed line kept and every alignment, the
Mermaid export writes the title in bold and the lines, the project bundle round trip carries them (an older bundle, and an
unknown value or an over-long title, is tidied on import) and the migration adds and drops the two columns. Every test builds
its own organisation."""

from __future__ import annotations

import io
import json
import re
import zipfile

from sqlalchemy import text

from alembic import command
from app.database import engine
from app.modules.architecture.diagram_svg import _note_block
from app.modules.architecture.enums import NOTE_TITLE_MAX
from app.modules.architecture.labels import NOTE_ALIGN_LABEL
from app.modules.architecture.schemas import NoteOut
from app.modules.architecture.tests._helpers import make_diagram, make_element, place_all, project_base, setup, view
from tests.conftest import auth_headers, build_alembic_config


def _diagram(client, token, project_id):
    a = make_element(client, token, project_id, "Alpha")
    diagram = place_all(client, token, project_id, make_diagram(client, token, project_id, "Text"), a["id"])
    return diagram, [{"element_id": a["id"], "x": 0, "y": 0}]


def _save(client, token, project_id, diagram, boxes, notes, *, expect=200):
    resp = client.put(
        f"{project_base(project_id)}/diagrams/{diagram['id']}/layout",
        json={"version": diagram["version"], "placements": boxes, "notes": notes}, headers=auth_headers(token),
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def _groups(client, token, project_id, diagram_id) -> list[str]:
    svg = client.get(f"{project_base(project_id)}/diagrams/{diagram_id}/svg", headers=auth_headers(token)).text
    return re.findall(r'<g data-note="[^"]+">(.*?)</g>', svg)


def test_a_title_up_to_the_limit_and_each_alignment_are_stored_and_returned(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch note text store")
    p = project["id"]
    diagram, boxes = _diagram(client, token, p)
    notes = [
        {"title": "T" * NOTE_TITLE_MAX, "text": "One\n\nTwo", "text_align": "right"},
        {"title": "Centred", "text": "x", "text_align": "center"},
        {"text": "No title"},
    ]
    saved = _save(client, token, p, diagram, boxes, notes)
    shown = view(client, token, p, diagram["id"])
    assert [(n["title"], n["text_align"]) for n in shown["notes"]] == [
        ("T" * NOTE_TITLE_MAX, "right"), ("Centred", "center"), ("", "left"),
    ]
    assert shown["notes"][0]["text"] == "One\n\nTwo"  # the typed line breaks are kept
    # Saving the same notes again changes nothing, and a changed alignment alone is a change.
    again = _save(client, token, p, saved, boxes, [{**n, "id": s["id"]} for n, s in zip(notes, shown["notes"], strict=True)])
    assert again["version"] == saved["version"]
    changed = [{**n, "id": s["id"]} for n, s in zip(notes, shown["notes"], strict=True)]
    changed[1]["text_align"] = "left"
    assert _save(client, token, p, again, boxes, changed)["version"] > again["version"]


def test_the_schema_refuses_a_title_over_the_limit_and_an_unknown_alignment(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch note text limits")
    p = project["id"]
    diagram, boxes = _diagram(client, token, p)
    _save(client, token, p, diagram, boxes, [{"title": "T" * (NOTE_TITLE_MAX + 1)}], expect=422)
    _save(client, token, p, diagram, boxes, [{"text_align": "justify"}], expect=422)
    assert set(NOTE_ALIGN_LABEL) == {"left", "center", "right"}


def test_the_svg_draws_the_title_in_bold_above_the_text_with_each_typed_line_and_the_alignment(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch note text svg")
    p = project["id"]
    diagram, boxes = _diagram(client, token, p)
    block = {"y": 200, "width": 200, "height": 120}
    _save(client, token, p, diagram, boxes, [
        {"title": "Heading", "text": "First line\n\nSecond <paragraph>", "x": 0, "text_align": "left", **block},
        {"title": "Mid", "text": "centred", "x": 300, "text_align": "center", **block},
        {"title": "End", "text": "right", "x": 600, "text_align": "right", **block},
    ])
    left, centre, right = _groups(client, token, p, diagram["id"])
    texts = re.findall(r"<text ([^>]*)>(.*?)</text>", left)
    assert [t[1] for t in texts] == ["Heading", "First line", "", "Second &lt;paragraph&gt;"]
    assert 'font-weight="bold"' in texts[0][0] and all('font-weight="bold"' not in t[0] for t in texts[1:])
    assert all('text-anchor="start"' in t[0] and 'x="6.0"' in t[0] for t in texts)
    assert 'text-anchor="middle"' in centre and 'x="400.0"' in centre  # 300 + 200 / 2
    assert 'text-anchor="end"' in right and 'x="794.0"' in right  # 600 + 200 - 6


def test_a_long_line_still_wraps_between_words_and_a_note_with_only_a_title_is_drawn(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch note text wrap")
    p = project["id"]
    diagram, boxes = _diagram(client, token, p)
    _save(client, token, p, diagram, boxes, [
        {"text": "alpha beta gamma delta epsilon zeta eta theta iota kappa", "x": 0, "y": 200, "width": 100, "height": 200},
        {"title": "Only a title", "tone": "none", "x": 300, "y": 200, "width": 160, "height": 60},
        {"tone": "none", "x": 600, "y": 200, "width": 160, "height": 60},
    ])
    groups = _groups(client, token, p, diagram["id"])
    assert len(groups) == 2  # the empty note with no tone is not drawn; the title alone is
    lines = [t for t in re.findall(r"<text [^>]*>(.*?)</text>", groups[0])]
    assert len(lines) > 1 and " ".join(lines) == "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    assert "Only a title" in groups[1]


def test_a_note_that_does_not_fit_ends_with_an_ellipsis_and_the_title_counts_as_lines(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch note text clip")
    p = project["id"]
    diagram, boxes = _diagram(client, token, p)
    _save(client, token, p, diagram, boxes, [{"title": "Title", "text": "a\nb\nc\nd\ne", "x": 0, "y": 200, "width": 200, "height": 60}])
    note = view(client, token, p, diagram["id"])["notes"][0]
    lines = _note_block(NoteOut.model_validate(note))
    assert len(lines) == 3 and lines[0] == ("Title", True) and lines[-1][0].endswith("…")


def test_mermaid_writes_the_title_in_bold_and_the_typed_lines(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch note text mermaid")
    p = project["id"]
    diagram, boxes = _diagram(client, token, p)
    _save(client, token, p, diagram, boxes, [{"title": "Head \"x\"", "text": "one\n\ntwo", "x": 0, "y": 200}])
    out = client.get(f"{project_base(p)}/diagrams/{diagram['id']}/mermaid", headers=auth_headers(token))
    assert out.status_code == 200
    note = next(line for line in out.text.splitlines() if line.startswith("    t1>"))
    assert note.startswith('    t1>"<b>Head ') and note.endswith('<br/>one<br/><br/>two"]')
    assert '"x"' not in note  # the quotes are escaped, so no label can end its string


def test_title_and_alignment_round_trip_through_the_project_bundle_and_an_older_bundle_gets_the_defaults(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch note text bundle")
    p = project["id"]
    diagram, boxes = _diagram(client, token, p)
    _save(client, token, p, diagram, boxes, [
        {"title": "Kept", "text": "a\n\nb", "text_align": "center", "x": 0, "y": 200}, {"text": "Plain", "x": 300, "y": 200},
    ])
    exported = client.get(f"/api/v1/projects/{p}/export", headers=auth_headers(token))
    archive = zipfile.ZipFile(io.BytesIO(exported.content))
    data = json.loads(archive.read("project.json"))
    entries = data["architecture_diagrams"][0]["notes"]
    assert (entries[0]["title"], entries[0]["text_align"]) == ("Kept", "center")
    # An older bundle has neither key, and a hand-edited one may have an unknown alignment or a long title.
    entries[1].pop("title", None)
    entries[1].pop("text_align", None)
    entries[0]["text_align"] = "justify"
    entries[0]["title"] = "T" * (NOTE_TITLE_MAX + 50)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as rewritten:
        for item in archive.infolist():
            rewritten.writestr(item, json.dumps(data) if item.filename == "project.json" else archive.read(item.filename))
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch note text bundle copy"},
        files={"file": ("bundle.zip", out.getvalue(), "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    copy = imported.json()["project"]
    listing = client.get(f"{project_base(copy['id'])}/diagrams", headers=auth_headers(token)).json()
    notes = view(client, token, copy["id"], listing[0]["id"])["notes"]
    assert [(n["title"], n["text_align"]) for n in notes] == [("T" * NOTE_TITLE_MAX, "left"), ("", "left")]
    assert notes[0]["text"] == "a\n\nb"


def test_the_note_text_migration_adds_the_columns_with_defaults_and_reverses_cleanly(client, admin_token):
    """Downgrading 0194 drops `title` and `text_align`; upgrading restores them as empty and `left` for every existing note."""
    _org, project, token = setup(client, admin_token, "Arch note text migration")
    p = project["id"]
    diagram, boxes = _diagram(client, token, p)
    _save(client, token, p, diagram, boxes, [{"title": "Kept", "text": "Kept too", "text_align": "right"}])
    note_id = view(client, token, p, diagram["id"])["notes"][0]["id"]
    command.downgrade(build_alembic_config(), "0193")
    try:
        with engine.connect() as conn:
            columns = {r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'architecture_diagram_notes'"
            ))}
            assert not {"title", "text_align"} & columns
            assert conn.execute(text("SELECT count(*) FROM architecture_diagram_notes WHERE id = :i"), {"i": note_id}).scalar_one() == 1
    finally:
        command.upgrade(build_alembic_config(), "head")
    with engine.connect() as conn:
        row = conn.execute(text("SELECT title, text_align FROM architecture_diagram_notes WHERE id = :i"), {"i": note_id}).one()
        assert tuple(row) == ("", "left")
        assert conn.execute(text(
            "SELECT count(*) FROM pg_constraint WHERE conname = 'ck_architecture_diagram_notes_text_align'"
        )).scalar_one() == 1
