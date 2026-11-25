"""Tests for Markdown fields in custom report layouts: a text block that is only a Markdown field's placeholder prints the
field formatted (headings below the layout's own, lists, code, tables, drawn diagrams); the same placeholder inside a
sentence or a table cell shows the field's words; a spreadsheet keeps the source; and nothing a record holds can change
what the layout prints around it. The evaluator tests build an organisation with the Decisions module on."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.database import SessionLocal
from app.models.organization import Organization
from app.models.project import Project
from app.modules.decisions.models import Decision
from app.services import report_diagram
from app.services.link_graph import ArtefactResolver
from app.services.report_diagram import DiagramError
from app.services.report_fields import field_catalogue
from app.services.report_framework import ReportContext
from app.services.report_layout_eval import evaluate_layout
from app.services.report_model import BulletList, CodeBlock, Gap, Grid, Heading, Image, Paragraph, Quote, Sheet, Table
from tests.link_world import World
from tests.test_report_layout_tree import doc

DECISION = "decision"
SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20"><rect width="40" height="20"/></svg>'
RATIONALE = (
    "# Why\n\nWe chose **PostgreSQL**.\n\n- cheap\n  - fast\n\n> board said\n\n```sql\nselect 1\n```\n\n"
    "| A | B |\n|---|---|\n| 1 | 2 |\n\n```mermaid\nflowchart LR\n A-->B\n```\n\n```mermaid\nbroken\n```\n"
)


def text(value: str) -> dict[str, Any]:
    return {"type": "text", "text": value}


def per_decision(*children: dict[str, Any]) -> dict[str, Any]:
    return doc({"type": "each", "source": {"record_type": DECISION}, "children": list(children)})


@pytest.fixture(autouse=True)
def _stub_converter(monkeypatch):
    def post(source: str, theme: str) -> bytes:
        if source == "broken":
            raise DiagramError("Parse error")
        return SVG.encode()

    monkeypatch.setattr(report_diagram, "_post", post)
    report_diagram.clear_cache()
    yield
    report_diagram.clear_cache()


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Markdown Eval Org", decisions=True)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


def decision_with(world: World, project: dict, code: str = "DEC-1", **fields: str) -> None:
    decision_id = world.decision(project, code)
    session = SessionLocal()
    try:
        record = session.get(Decision, decision_id)
        for name, value in fields.items():
            setattr(record, name, value)
        session.commit()
    finally:
        session.close()


def run(db, world: World, project: dict, tree: dict[str, Any]):
    row = db.get(Project, uuid.UUID(project["id"]))
    org = db.get(Organization, uuid.UUID(world.org["id"]))
    resolver = ArtefactResolver(db, row, world.user_id, include_related=True)
    ctx = ReportContext(module_key="reporting", organization=org, projects=[row], root_project=row)
    return evaluate_layout(db, resolver, ctx, tree, title="Report")


def blocks_of(result) -> list:
    return [b for b in result.document.blocks if not isinstance(b, Gap)]


def test_the_decision_text_fields_and_the_document_are_declared_markdown_in_the_field_registry():
    info = {f.key: f for f in field_catalogue(DECISION)}

    assert all(info[key].markdown for key in ("rationale", "context", "decision_statement", "document"))
    assert not info["title"].markdown and not info["decision_type"].markdown


def test_a_paragraph_that_is_only_a_markdown_field_prints_formatted_with_its_diagrams_drawn(world, db):
    project = world.project("Formatted P")
    decision_with(world, project, rationale=RATIONALE)

    result = run(db, world, project, per_decision(text("{{record.rationale}}")))
    found = blocks_of(result)

    assert [type(b) for b in found] == [Heading, Paragraph, BulletList, Quote, CodeBlock, Grid, Image, CodeBlock]
    assert (found[0].text, found[0].level) == ("Why", 3)  # `#` in a record sits below the layout's own headings
    assert found[2].items == ["cheap", "fast"] and found[2].levels == (0, 1)
    assert found[4] == CodeBlock("select 1", "sql")
    assert found[6].raster and found[6].svg and found[6].alt == "Diagram (flowchart)"
    assert found[7].text == "broken" and "could not be drawn" in found[7].label
    assert any("A diagram is shown as its text" in warning for warning in result.warnings)


def test_the_document_field_prints_the_same_way(world, db):
    project = world.project("Document P")
    decision_with(world, project, document="## Detail\n\nLong *argument*.\n")

    found = blocks_of(run(db, world, project, per_decision(text("{{record.document}}"))))

    assert [type(b) for b in found] == [Heading, Paragraph] and found[0].level == 4


def test_in_a_sentence_or_a_cell_the_field_shows_its_words_not_its_marks(world, db):
    project = world.project("Words P")
    decision_with(world, project, rationale="We chose **PostgreSQL**.\n\n- cheap\n\n```mermaid\nflowchart LR\n A-->B\n```\n")
    tree = per_decision(text("Because: {{record.rationale}}"), {
        "type": "table", "source": {"record_type": DECISION}, "columns": [{"field": "rationale"}],
    })

    found = blocks_of(run(db, world, project, tree))

    assert found[0] == Paragraph("Because: We chose PostgreSQL. cheap Diagram")
    table = next(b for b in found if isinstance(b, Table))
    assert table.rows[0][0] == "We chose PostgreSQL. cheap Diagram"


def test_a_spreadsheet_keeps_the_markdown_source(world, db):
    project = world.project("Sheet P")
    decision_with(world, project, rationale="We chose **PostgreSQL**.")
    tree = {"schema_version": 1, "family": "table", "nodes": [
        {"type": "sheet", "name": "Decisions", "source": {"record_type": DECISION}, "columns": [{"field": "rationale"}]},
    ]}

    result = run(db, world, project, tree)

    assert isinstance(result.sheets[0], Sheet) and result.sheets[0].rows[0][0] == "We chose **PostgreSQL**."


def test_nothing_in_a_record_can_add_a_placeholder_a_style_or_a_heading_to_the_layout(world, db):
    project = world.project("Hostile P")
    decision_with(world, project, rationale="{{record.title}} and {{project_name}}", context="<script>x</script> [a](javascript:alert(1))")
    tree = per_decision(text("{{record.rationale}}"), text("{{record.context}}"), text("**{{record.title}}**"))

    found = blocks_of(run(db, world, project, tree))

    assert found[0] == Paragraph("{{record.title}} and {{project_name}}")  # a value is never filled in
    assert str(found[1].text) == "<script>x</script> [a](javascript:alert(1))"  # shown as typed: no markup, no link
    assert not any(getattr(p, "href", None) for p in getattr(found[1].text, "parts", ()))


def test_a_layouts_own_diagram_is_drawn_once_however_many_records_it_runs_over(world, db, monkeypatch):
    project = world.project("Own P")
    decision_with(world, project, rationale="x")
    world.decision(project, "DEC-2")
    asked: list[str] = []
    monkeypatch.setattr(report_diagram, "_post", lambda source, theme: asked.append(source) or SVG.encode())
    tree = per_decision(text("```mermaid\nflowchart LR\n A-->B\n```\n"))

    found = blocks_of(run(db, world, project, tree))

    assert [type(b) for b in found] == [Image, Image] and asked == ["flowchart LR\n A-->B"]


def test_when_the_converter_is_not_available_the_run_still_completes_with_the_source_and_one_warning(world, db, monkeypatch):
    project = world.project("Down P")
    decision_with(world, project, rationale="```mermaid\nflowchart LR\n A-->B\n```\n\n```mermaid\nflowchart LR\n C-->D\n```\n")
    monkeypatch.setattr(report_diagram, "_post", lambda source, theme: (_ for _ in ()).throw(DiagramError(report_diagram.UNAVAILABLE)))

    result = run(db, world, project, per_decision(text("{{record.rationale}}")))

    assert [type(b) for b in blocks_of(result)] == [CodeBlock, CodeBlock]
    assert result.warnings == [f"A diagram is shown as its text. {report_diagram.UNAVAILABLE}"]


# ---- the cost of long text and diagrams --------------------------------------------------------------------------------

LONG_TEXT = (
    "# Section\n\n" + "A paragraph of **long** text with a `span`. " * 40 + "\n\n- item\n  - nested\n\n```mermaid\nflowchart LR\n A-->B\n```\n"
)


def count_statements(db, world: World, project: dict, tree: dict[str, Any]) -> int:
    from sqlalchemy import event

    from app.database import engine

    seen: list[str] = []

    def record(_conn, _cursor, statement, *_args, **_kwargs) -> None:
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        run(db, world, project, tree)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return len(seen)


def test_a_report_of_many_decisions_with_long_text_reads_flat_and_draws_each_distinct_diagram_once(world, db, monkeypatch):
    """The probe for Markdown in reports: the statements behind a run do not grow with the records it prints, and the converter
    is asked once per distinct diagram, not once per record."""
    asked: list[str] = []
    monkeypatch.setattr(report_diagram, "_post", lambda source, theme: asked.append(source) or SVG.encode())
    small, large = world.project("Probe small"), world.project("Probe large")
    for number in range(4):
        decision_with(world, small, f"DEC-{number + 1}", rationale=LONG_TEXT)
    for number in range(16):
        decision_with(world, large, f"DEC-{number + 1}", rationale=LONG_TEXT)
    tree = per_decision(text("{{record.rationale}}"), text("{{record.title}}: {{record.rationale}}"))
    run(db, world, small, tree)  # warms the per-process caches (registry, catalogue) both measurements share
    report_diagram.clear_cache()
    asked.clear()

    few, many = count_statements(db, world, small, tree), count_statements(db, world, large, tree)

    assert few == many, "the statements behind a run grew with the number of records"
    assert asked == ["flowchart LR\n A-->B"]  # drawn once for the first run, then served from the cache, never once per record
