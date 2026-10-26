"""Tests for equations in layouts: the `equation` block and `\\( \\)` / `$$ $$` in text (validation, the text view's
exact round trip), and the evaluator's rule that math is recognised only in the author's text and in the value of
a math-capable record field, never in another record value. Validation and text view need no database; the
evaluator tests build an organisation."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.database import SessionLocal
from app.models.organization import Organization
from app.models.project import Project
from app.services import report_layout_eval
from app.services.link_graph import ArtefactResolver
from app.services.report_fields import field_catalogue
from app.services.report_framework import ReportContext
from app.services.report_layout_eval import MAX_EQUATIONS, evaluate_layout
from app.services.report_layout_text import TEXT_FORMS, format_tree, parse_text
from app.services.report_layout_tree import BLOCK_SPECS, tree_hash, validate_tree
from app.services.report_model import Equation, Gap, MathText, Paragraph
from tests.conftest import auth_headers
from tests.link_world import REQ, World
from tests.test_report_layout_tree import doc, errors


def equation(tex: str) -> dict[str, Any]:
    return {"type": "equation", "tex": tex}


def text(value: str) -> dict[str, Any]:
    return {"type": "text", "text": value}


# --- validation ------------------------------------------------------------------------------------


def test_the_equation_block_is_registered_everywhere_a_block_must_be():
    assert "equation" in BLOCK_SPECS and "equation" in TEXT_FORMS
    assert "equation" in report_layout_eval._EVALUATORS


def test_a_valid_equation_block_passes():
    assert validate_tree(doc(equation(r"\frac{a}{b} = c"))).ok


@pytest.mark.parametrize("tree, path", [
    (doc({"type": "equation"}), "nodes[0].tex"),
    (doc(equation("")), "nodes[0].tex"),
    (doc(equation(r"\href{http://x}{y}")), "nodes[0].tex"),
    (doc(equation(" x ")), "nodes[0].tex"),
    (doc(equation("a\nb")), "nodes[0].tex"),
    (doc(equation("x" * 2001)), "nodes[0].tex"),
    (doc({"type": "equation", "tex": "x", "display": True}), "nodes[0].display"),
    (doc({"type": "equation", "tex": 5}), "nodes[0].tex"),
])
def test_an_invalid_equation_block_is_refused_at_its_path(tree, path):
    assert path in errors(tree)


def test_an_equation_is_a_document_block_not_a_sheet_block():
    tree = {"schema_version": 1, "family": "table", "nodes": [equation("x")]}

    assert errors(tree)


def test_an_equation_written_in_text_is_checked_on_save():
    found = errors(doc(text(r"Fine \(x\) then \(\input{/etc/passwd}\) and $$\href{u}{v}$$")))

    assert "An equation in the text" in found["nodes[0].text"]
    assert validate_tree(doc(text(r"Fine \(x\) and $$\frac{a}{b}$$"))).ok


def test_an_equation_written_in_a_heading_is_checked_on_save():
    found = errors(doc({"type": "heading", "text": r"Bad \(\input{x}\)"}))

    assert "An equation in the text" in found["nodes[0].text"]
    assert validate_tree(doc({"type": "heading", "text": r"Fine \(x^2\)"})).ok


def test_an_equation_in_text_that_holds_a_placeholder_is_checked_only_when_it_runs():
    assert validate_tree(doc(text(r"\(x = {{project_name}}\)"))).ok


def test_stray_delimiters_in_text_are_not_errors():
    assert validate_tree(doc(text(r"costs $5, a lone \) and an open \(x"))).ok


# --- the text view ---------------------------------------------------------------------------------


@pytest.mark.parametrize("tex", [
    "x", r"\frac{a}{b}", "a  +  b", r"\begin{pmatrix}a&b\\c&d\end{pmatrix}", "x@y", "a' + b'", r"\text{end}",
    "{{x}}", "x^{{2}}",
])
def test_an_equation_reads_back_from_its_text_exactly(tex):
    tree = doc({"type": "heading", "text": "H"}, equation(tex), text("after"))
    assert validate_tree(tree).ok, validate_tree(tree).errors
    written = format_tree(tree)
    parsed = parse_text(written)

    assert parsed.errors == [] and parsed.tree == tree
    assert tree_hash(parsed.tree) == tree_hash(tree)
    assert f"@equation {tex}" in written


def test_an_equation_inside_a_container_keeps_its_indentation():
    tree = doc({"type": "each", "source": {"record_type": REQ}, "children": [equation(r"x^2"), text("t")]})
    written = format_tree(tree)

    assert "  @equation x^2" in written and parse_text(written).tree == tree


def test_text_holding_math_delimiters_reads_back_unchanged():
    tree = doc(text("Where \\(x\\) is the load\n\n$$\ny = mx + c\n$$"), text("a $5 and \\( b"))
    parsed = parse_text(format_tree(tree))

    assert parsed.errors == [] and parsed.tree == tree


def test_an_equation_with_no_tex_is_a_syntax_error_at_its_line():
    result = parse_text("@layout document\n@equation\n")

    assert result.tree is None and [(e.line, "TeX" in e.message) for e in result.errors] == [(2, True)]


def test_a_disallowed_command_is_reported_at_the_line_of_the_block():
    result = parse_text("@layout document\n\n@heading Title\n@equation \\input{/etc/passwd}\n")

    assert [(e.line, "not supported" in e.message) for e in result.errors] == [(4, True)]


# --- the field registry ---------------------------------------------------------------------------


def test_requirement_text_fields_are_math_capable_and_the_title_is_not():
    info = {f.key: f for f in field_catalogue(REQ)}

    assert info["description"].math and info["reasoning"].math and info["clarification"].math
    assert not info["title"].math and not info["component"].math


# --- evaluation ------------------------------------------------------------------------------------


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Math Eval Org")


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
        session.rollback()
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


def make_requirement(world: World, project: dict, name: str, description: str = "") -> None:
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": name, "description": description, "component_id": project["component_id"], "category_id": project["category_id"]},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text


def runs(block) -> list:
    """The runs of a block's text: plain pieces and inline equations (a plain string is one run)."""
    return list(block.text.parts) if isinstance(block.text, MathText) else [block.text]


def per_requirement(*children: dict[str, Any]) -> dict[str, Any]:
    return doc({"type": "each", "source": {"record_type": REQ}, "children": list(children)})


def test_authored_inline_and_display_math_becomes_equation_blocks(world, db):
    project = world.project("Authored P")
    tree = doc(text(r"The load \(F = m a\) is the force."), text("$$E = m c^2$$"), text("mixed \\(x\\) and\n$$y$$\nend"))

    found = blocks_of(run(db, world, project, tree))

    assert runs(found[0]) == ["The load ", Equation("F = m a", False), " is the force."]
    assert found[1] == Equation("E = m c^2", True)
    assert runs(found[2]) == ["mixed ", Equation("x", False), " and\n"]
    assert found[3] == Equation("y", True) and found[4] == Paragraph("\nend")


def test_text_without_math_is_the_plain_paragraph_it_always_was(world, db):
    project = world.project("Plain P")

    found = blocks_of(run(db, world, project, doc(text("costs $5 and \\( open"))))

    assert found == [Paragraph("costs $5 and \\( open")]


def test_the_equation_block_emits_a_display_equation(world, db):
    project = world.project("Block P")

    found = blocks_of(run(db, world, project, doc(equation(r"\frac{a}{b}"))))

    assert found == [Equation(r"\frac{a}{b}", True)]


def test_a_math_capable_field_value_is_scanned_and_another_value_is_not(world, db):
    project = world.project("Field P")
    make_requirement(world, project, r"Title \(x\) $$y$$", description=r"Stress \(\sigma = F/A\) holds")
    tree = per_requirement(text("{{record.description}}"), text("{{record.title}}"))

    found = blocks_of(run(db, world, project, tree))

    assert runs(found[0]) == ["Stress ", Equation(r"\sigma = F/A", False), " holds"]
    assert found[1] == Paragraph(r"Title \(x\) $$y$$")  # the title is not math-capable: shown as written


def test_authored_delimiters_around_a_value_that_is_not_math_capable_still_work(world, db):
    project = world.project("Around P")
    make_requirement(world, project, "n")
    tree = per_requirement(text(r"\(k = {{record.title}}\)"))

    found = blocks_of(run(db, world, project, tree))

    assert [runs(b) for b in found] == [[Equation("k = n", False)]]


def test_a_closing_delimiter_inside_a_plain_value_does_not_close_the_authors_equation(world, db):
    project = world.project("Closer P")
    make_requirement(world, project, r"x \) $$ y")
    tree = per_requirement(text(r"\(k = {{record.title}}"))

    found = blocks_of(run(db, world, project, tree))

    assert found == [Paragraph(r"\(k = x \) $$ y")]  # no authored closer: ordinary text


def test_tex_that_may_not_be_drawn_is_shown_as_written_with_one_warning_that_never_quotes_it(world, db):
    project = world.project("Bad P")
    make_requirement(world, project, "n", description=r"Bad \(\href{http://secret.example}{x}\) twice \(\input{y}\)")
    tree = per_requirement(text("{{record.description}}"), equation(r"\frac{a}"))

    result = run(db, world, project, tree)
    found = blocks_of(result)

    assert found[0] == Paragraph(r"Bad \(\href{http://secret.example}{x}\) twice \(\input{y}\)")
    assert found[1] == Paragraph(r"$$\frac{a}$$")  # allowed commands, but not drawable TeX
    assert result.warnings == ["An equation could not be drawn and is shown as written."]
    assert "secret.example" not in " ".join(result.warnings)


def test_headings_list_items_and_table_cells_draw_equations_too(world, db):
    project = world.project("Elsewhere P")
    make_requirement(world, project, "n", description=r"\(x\) and $$y$$")
    tree = per_requirement(
        {"type": "heading", "text": r"H \(a\) {{record.title}}"}, text(r"- item \(b\)"),
        {"type": "table", "source": {"record_type": REQ}, "columns": [{"field": "description"}, {"field": "title"}]},
    )

    found = blocks_of(run(db, world, project, tree))

    assert runs(found[0]) == ["H ", Equation("a", False), " n"] and found[0].level == 1
    assert [list(i.parts) if isinstance(i, MathText) else i for i in found[1].items] == [["item ", Equation("b", False)]]
    cell, title = found[2].rows[0]
    assert list(cell.parts) == [Equation("x", False), " and ", Equation("y", False)]  # `$$ $$` here is drawn inline
    assert title == "n" and not isinstance(title, MathText)
    assert cell == r"\(x\) and \(y\)"  # a string-only consumer sees the source (an inline `$$ $$` as `\( \)`)


def test_a_title_in_a_heading_or_a_cell_is_never_read_as_math(world, db):
    project = world.project("Titles P")
    make_requirement(world, project, r"T \(x\)")
    tree = per_requirement(
        {"type": "heading", "text": "{{record.title}}"},
        {"type": "table", "source": {"record_type": REQ}, "columns": [{"field": "title"}]},
    )

    found = blocks_of(run(db, world, project, tree))

    assert not isinstance(found[0].text, MathText) and found[0].text == r"T \(x\)"
    assert not isinstance(found[1].rows[0][0], MathText)


def test_a_cell_that_cannot_be_drawn_shows_its_source_with_a_warning(world, db):
    project = world.project("Bad cell P")
    make_requirement(world, project, "n", description=r"\(\href{u}{v}\)")
    tree = per_requirement({"type": "table", "source": {"record_type": REQ}, "columns": [{"field": "description"}]})

    result = run(db, world, project, tree)

    assert blocks_of(result)[0].rows == [[r"\(\href{u}{v}\)"]]
    assert result.warnings == ["An equation could not be drawn and is shown as written."]


def test_the_sheets_of_a_table_layout_keep_tex_as_text(world, db):
    project = world.project("Sheet P")
    make_requirement(world, project, "n", description=r"\(x\)")
    tree = {"schema_version": 1, "family": "table", "nodes": [
        {"type": "sheet", "name": "S", "source": {"record_type": REQ}, "columns": [{"field": "description"}]},
    ]}

    result = run(db, world, project, tree)

    assert result.sheets[0].rows == [[r"\(x\)"]] and not isinstance(result.sheets[0].rows[0][0], MathText)


def test_a_run_draws_a_bounded_number_of_equations(world, db, monkeypatch):
    project = world.project("Cap P")
    monkeypatch.setattr(report_layout_eval, "MAX_EQUATIONS", 3)
    tree = doc(*[equation(f"x_{i}") for i in range(5)])

    result = run(db, world, project, tree)
    found = blocks_of(result)

    assert [type(b).__name__ for b in found] == ["Equation"] * 3 + ["Paragraph"] * 2
    assert found[3] == Paragraph("$$x_3$$")
    assert result.warnings == ["A run draws at most 3 equations; the rest are shown as written."]
    assert MAX_EQUATIONS == 1000


def test_the_same_equation_per_record_is_drawn_once_and_counted_per_use(world, db):
    project = world.project("Repeat P")
    for name in ("a", "b"):
        make_requirement(world, project, name)
    tree = per_requirement(text(r"\(x^2\) for {{record.title}}"))

    found = blocks_of(run(db, world, project, tree))

    assert [isinstance(b.text, MathText) for b in found] == [True, True]
