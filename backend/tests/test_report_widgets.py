"""Tests for widgets in custom report layouts: the catalogue (`services.report_widgets`), the `widget` block in
the tree, the evaluator and the text view `[[widget.<module>.<report>.<part> name=value]]`. A widget is one
component of a report (a table, its headline figures, its notes); the words around it are the layout's.

The catalogue, validator and text view need no database; the evaluator, provenance and routes build their own
organisation.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.database import SessionLocal
from app.models.generated_report import GeneratedReport
from app.models.organization import Organization
from app.models.project import Project
from app.modules.registry import BUILT_IN_REPORT_PARTS, ReportDefinition, ReportParamDefinition, get_all_reports
from app.services import report_layout_eval, report_widget_run, report_widgets
from app.services.link_graph import ArtefactResolver
from app.services.report_framework import ReportContext, ReportResult, ReportSection
from app.services.report_layout_eval import evaluate_layout
from app.services.report_layout_text import TEXT_FORMS, format_tree, parse_text
from app.services.report_layout_tree import BLOCK_SPECS, MAX_WIDGET_REPORTS, assert_valid, empty_tree, validate_tree
from app.services.report_model import Gap, Heading, Note, Table
from app.services.report_widget_run import output_digest, part_blocks
from tests.conftest import auth_headers
from tests.link_world import World

SUMMARY = "context_strategy.summary.figures"
SUMMARY_NOTES = "context_strategy.summary.notes"
REGISTER = "decisions.decision-register.register"
BY_STATUS = "decisions.decision-register.by_status"
POWER_GRID = "stakeholders.power-interest-grid.manage_closely"
RISKS = "risk_management.risk-register.register"
COVERAGE_MATRIX = "context_strategy.pain-point-coverage.matrix"
UUID_A = "3f2b8c1e-9d4a-4c55-8f0e-2a6d7b1c9e40"


def doc(*nodes: dict[str, Any]) -> dict[str, Any]:
    return {**empty_tree("document"), "nodes": list(nodes)}


def widget(key: str, **params: Any) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "widget", "key": key}
    if params:
        node["params"] = params
    return node


def errors_of(tree: dict[str, Any]) -> list[tuple[str, str]]:
    return [(e.path, e.message) for e in validate_tree(tree).errors]


def fake_widget(*params: ReportParamDefinition) -> report_widgets.WidgetInfo:
    """A widget over a made-up report, to test parameter handling for every declared type."""

    def collector(db: Any, ctx: ReportContext) -> ReportResult:
        raise AssertionError("the parameter tests never run the report")

    definition = ReportDefinition(key="x", slug="fake", title="Fake", description="d", collector=collector, params=params)
    return report_widgets.WidgetInfo("fake_module.fake.table", "fake_module", "Fake module", definition, report_widgets.BUILT_IN_PARTS[0])


# ---- the catalogue ----------------------------------------------------------------------------------------------


def test_every_report_offers_its_declared_tables_plus_the_figures_and_the_notes():
    widgets = report_widgets.list_widgets()

    expected = [
        f"{m}.{d.slug}.{part}"
        for m, d in get_all_reports()
        for part in [*(p.key for p in d.parts), *BUILT_IN_REPORT_PARTS]
    ]
    assert [w.key for w in widgets] == expected
    assert len({w.key for w in widgets}) == len(widgets)
    assert all(report_widgets.WIDGET_KEY_RE.match(w.key) for w in widgets)
    assert [p.key for p in report_widgets.BUILT_IN_PARTS] == list(BUILT_IN_REPORT_PARTS)


def test_a_widget_knows_its_report_its_part_and_the_reports_parameters():
    register = report_widgets.find_widget(REGISTER)
    figures = report_widgets.find_widget(SUMMARY)

    assert register.part.kind == "section" and register.part.key == "register" and register.title == "Decisions"
    assert register.report_title == "Decision register" and register.report_key == "decisions.decision-register"
    assert figures.part.kind == "figures" and figures.report_key == "context_strategy.summary"
    assert report_widgets.find_widget(SUMMARY_NOTES).part.kind == "notes"
    # Every component of a report takes the report's own parameters.
    assert report_widgets.find_widget(BY_STATUS).params == register.params and register.params


@pytest.mark.parametrize(
    "key", ["", "summary", "context_strategy.summary", "context_strategy.", ".summary", "Context.summary.figures", "a.b.c.d", "x y.z.w", None, 5],
)
def test_a_key_that_is_not_a_widget_key_finds_nothing(key):
    assert report_widgets.find_widget(key) is None  # type: ignore[arg-type]


def test_a_part_the_report_does_not_have_is_not_a_widget():
    assert report_widgets.find_widget("decisions.decision-register.nothing") is None
    assert report_widgets.find_widget("decisions.nothing.register") is None


@pytest.mark.parametrize(
    ("param", "good", "bad"),
    [
        (ReportParamDefinition("p", "string"), ["x", "a b"], ["", "  ", 5, True, "x" * 201]),
        (ReportParamDefinition("p", "string", choices=("a", "b")), ["a"], ["c"]),
        (ReportParamDefinition("p", "integer", minimum=1, maximum=10), [1, 10], [0, 11, 1.5, "3", True]),
        (ReportParamDefinition("p", "boolean"), [True, False], ["true", 1, None]),
        (ReportParamDefinition("p", "date"), ["2026-10-26"], ["2026-13-01", "26/10/2026", "2026-10-26T00:00:00Z", 20261026]),
        (ReportParamDefinition("p", "uuid"), [UUID_A], [UUID_A.upper(), UUID_A.replace("-", ""), "nope", 5]),
    ],
)
def test_a_parameter_value_must_be_a_literal_of_its_declared_type(param, good, bad):
    info = fake_widget(param)

    for value in good:
        assert report_widgets.param_problems(info, {"p": value}) == [], value
    for value in bad:
        problems = report_widgets.param_problems(info, {"p": value})
        assert len(problems) == 1 and problems[0][0] == "p", value


def test_parameters_that_are_not_declared_or_are_empty_are_refused():
    info = fake_widget(ReportParamDefinition("known", "string"))

    assert report_widgets.param_problems(info, {"other": "x"})[0][1].startswith("This report has no parameter 'other'")
    assert "Its parameters: known" in report_widgets.param_problems(info, {"other": "x"})[0][1]
    assert report_widgets.param_problems(info, {}) == [("", "Leave params out when no parameter is set.")]
    assert report_widgets.param_problems(info, ["known"]) == [("", "Must be an object of parameter values.")]


def test_typed_params_fill_defaults_and_convert_dates_and_ids():
    info = fake_widget(
        ReportParamDefinition("when", "date"), ReportParamDefinition("who", "uuid"),
        ReportParamDefinition("months", "integer", default=6), ReportParamDefinition("name", "string"),
    )

    typed = report_widgets.typed_params(info, {"when": "2026-10-26", "who": UUID_A})

    assert typed == {"when": date(2026, 10, 26), "who": uuid.UUID(UUID_A), "months": 6, "name": None}
    assert report_widgets.typed_params(info, None)["months"] == 6


# ---- the block in the tree --------------------------------------------------------------------------------------


def test_a_widget_with_declared_parameters_is_valid():
    tree = doc(widget(SUMMARY, stale_months=12, since="2026-01-01", rollup="worst_case"), widget(REGISTER, include_archived=True))

    assert_valid(tree)


def test_a_widget_without_parameters_is_valid_and_empty_params_are_not():
    assert_valid(doc(widget(SUMMARY)))
    assert errors_of(doc({"type": "widget", "key": SUMMARY, "params": {}})) == [("nodes[0].params", "Leave params out when no parameter is set.")]


def test_an_unknown_widget_lists_the_ones_that_exist():
    (path, message), = errors_of(doc(widget("nope.nothing")))

    assert path == "nodes[0].key"
    assert 'Unknown widget "nope.nothing"' in message and SUMMARY in message and REGISTER in message


def test_a_widget_error_is_positioned_at_the_parameter():
    errors = dict(errors_of(doc(
        widget(SUMMARY, stale_months=0, rollup="best", nonsense=1),
        {"type": "widget"},
    )))

    assert errors["nodes[0].params.stale_months"] == "Must be at least 1."
    assert errors["nodes[0].params.rollup"].startswith("Must be one of: weighted_average")
    assert "no parameter 'nonsense'" in errors["nodes[0].params.nonsense"]
    assert errors["nodes[1].key"] == "Required."


def test_unknown_keys_on_a_widget_block_are_refused():
    assert ("nodes[0].level", "Unknown key.") in errors_of(doc({"type": "widget", "key": SUMMARY, "level": 3}))


def test_a_widget_may_carry_text_for_when_it_is_empty_and_only_global_placeholders_in_it():
    assert_valid(doc({"type": "widget", "key": REGISTER, "empty_text": "No decisions for {{project_name}}."}))
    assert errors_of(doc({"type": "widget", "key": REGISTER, "empty_text": "  "})) == [("nodes[0].empty_text", "Must not be empty.")]
    assert errors_of(doc({"type": "widget", "key": REGISTER, "empty_text": "{{req.title}}"}))[0][0] == "nodes[0].empty_text"


def test_widgets_of_one_report_with_the_same_settings_share_a_run_and_so_do_not_count_again():
    same_report = doc(*[widget(key) for key in (SUMMARY, SUMMARY_NOTES, SUMMARY, SUMMARY_NOTES)] * 10)

    assert_valid(same_report)


def test_a_layout_may_run_only_so_many_different_reports():
    ok = doc(*[widget(SUMMARY, stale_months=i + 1) for i in range(MAX_WIDGET_REPORTS)])
    too_many = doc(*[widget(SUMMARY, stale_months=i + 1) for i in range(MAX_WIDGET_REPORTS + 1)])

    assert_valid(ok)
    (path, message), = errors_of(too_many)
    assert path == f"nodes[{MAX_WIDGET_REPORTS}]" and f"limit is {MAX_WIDGET_REPORTS}" in message


def test_a_table_layout_cannot_hold_a_widget():
    tree = {**empty_tree("table"), "nodes": [widget(SUMMARY)]}

    assert errors_of(tree) == [("nodes[0].type", "A widget block cannot be used in a table layout.")]


def test_a_widget_may_sit_inside_a_block():
    tree = doc({"type": "each", "source": {"record_type": "requirement"}, "children": [widget(SUMMARY)]})

    assert_valid(tree)


# ---- the text view ----------------------------------------------------------------------------------------------


def roundtrip(tree: dict[str, Any]) -> str:
    text = format_tree(tree)
    result = parse_text(text)
    assert result.ok, (text, result.errors)
    assert result.tree == tree, text
    assert format_tree(result.tree) == text
    return text


def test_a_widget_is_one_bracketed_line():
    text = roundtrip(doc(widget(SUMMARY, stale_months=12, since="2026-01-01", rollup="worst_case")))

    assert '[[widget.context_strategy.summary.figures stale_months=12 since=2026-01-01 rollup=worst_case]]' in text


def test_a_widget_without_parameters_has_no_trailing_space():
    assert "[[widget.context_strategy.summary.figures]]" in roundtrip(doc(widget(SUMMARY)))


def test_the_empty_text_is_a_clause_after_the_settings_and_reads_back_exactly():
    tree = doc(
        {"type": "widget", "key": REGISTER, "params": {"status": "approved"}, "empty_text": 'No "approved" decisions yet.'},
        {"type": "widget", "key": BY_STATUS, "empty_text": "None."},
        {"type": "widget", "key": SUMMARY, "params": {"stale_months": 3}, "empty_text": "x=1 empty \"y\" ]]"},
    )

    text = roundtrip(tree)

    assert '[[widget.decisions.decision-register.register status=approved empty "No \\"approved\\" decisions yet."]]' in text
    assert '[[widget.decisions.decision-register.by_status empty "None."]]' in text


def test_empty_must_be_followed_by_quoted_text_and_given_once():
    base = "@layout document\n\n[[widget.decisions.decision-register.register {}]]\n"

    assert "Expected name=value" in parse_text(base.format("empty none")).errors[0].message
    assert "is given twice" in parse_text(base.format('empty "a" empty "b"')).errors[0].message
    assert "never closed" in parse_text(base.format('empty "a')).errors[0].message
    assert parse_text(base.format('empty="x"')).errors[0].message.startswith("Expected name=value") is False  # a parameter called empty



def test_values_are_bare_only_when_they_read_back_as_the_same_value():
    tree = doc(
        widget(REGISTER, status="draft", date_from="2026-01-01", date_to="2026-12-31", include_archived=True, decision_type="1"),
        widget(REGISTER, decision_type="true"),
        widget(REGISTER, decision_type="12.5"),
        widget(REGISTER, decision_type="a b"),
        widget(REGISTER, decision_type='quote " and ] and \\'),
        widget(REGISTER, decision_type="]]"),
        widget(REGISTER, decision_type="ünïcode"),
        widget(REGISTER, decision_type="x=y"),
        widget(POWER_GRID, group_id=UUID_A),
    )

    text = roundtrip(tree)

    assert 'decision_type="1"' in text and 'decision_type="true"' in text and 'decision_type="12.5"' in text
    assert "status=draft" in text and "include_archived=true" in text and f"group_id={UUID_A}" in text


def test_a_widget_among_other_blocks_reads_back_exactly():
    tree = doc(
        {"type": "heading", "text": "Summary"},
        widget(SUMMARY),
        {"type": "text", "text": "Between."},
        widget(REGISTER, status="approved"),
        {"type": "each", "source": {"record_type": "requirement"}, "as": "req", "children": [
            {"type": "text", "text": "{{req.title}}"}, {"type": "page_break"},
        ]},
    )

    text = roundtrip(tree)

    assert "\n[[widget.decisions.decision-register.register status=approved]]\n" in text


def test_prose_that_looks_like_a_widget_line_stays_prose_through_the_text_view():
    lookalikes = (
        "[[widget.context_strategy.summary.figures]]", "  [[widget.nothing]]", "[[widget", "[[widgets are nice]]",
        "[[widget.x y=1]] and more",
    )
    for line in lookalikes:
        roundtrip(doc({"type": "text", "text": line}, widget(SUMMARY), {"type": "text", "text": f"before\n{line}\nafter"}))


def test_a_widget_line_in_plain_text_is_a_widget_not_prose():
    result = parse_text("@layout document\n\nSome prose.\n[[widget.context_strategy.summary.figures]]\nMore prose.\n")

    assert result.ok
    assert [n["type"] for n in result.tree["nodes"]] == ["text", "widget", "text"]


def test_text_that_is_not_a_widget_start_is_ordinary_prose():
    result = parse_text("@layout document\n\n[[note]] and [[widgety]]\n")

    assert result.ok and result.tree["nodes"] == [{"type": "text", "text": "[[note]] and [[widgety]]"}]


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("[[widget.context_strategy.summary.figures", "must end with ]]"),
        ("[[widget.context_strategy.summary.figures]] trailing", "must end with ]]"),
        ("[[widget context_strategy.summary.figures]]", "with a dot after widget"),
        ("[[widget]]", "with a dot after widget"),
        ("[[widget.]]", "Name the component"),
        ("[[widget. ]]", "Name the component"),
        ("[[widget.context_strategy.summary.figures stale_months]]", "Expected name=value"),
        ("[[widget.context_strategy.summary.figures stale_months=]]", "needs a value"),
        ("[[widget.context_strategy.summary.figures stale_months= 3]]", "needs a value"),
        ("[[widget.context_strategy.summary.figures stale_months=3 stale_months=4]]", "is given twice"),
        ('[[widget.context_strategy.summary.figures since="2026]]', "never closed"),
        ('[[widget.context_strategy.summary.figures since="\\q"]]', "Not valid quoted text"),
        ('[[widget.context_strategy.summary.figures a"b"=1]]', "Expected name=value"),
        ("[[widget.context_strategy.summary.figures Stale=1]]", "Expected name=value"),
    ],
)
def test_a_malformed_widget_line_is_a_syntax_error_at_its_line(line, message):
    result = parse_text(f"@layout document\n\n{line}\n")

    assert result.tree is None
    assert len(result.errors) == 1 and result.errors[0].line == 3 and message in result.errors[0].message


def test_a_widget_error_from_the_validator_is_reported_at_the_widgets_line():
    result = parse_text("@layout document\n\n# text\n[[widget.nope.nothing]]\n[[widget.context_strategy.summary.figures stale_months=0]]\n")

    assert result.tree is not None and not result.ok
    assert [(e.line, e.message.split(":")[0]) for e in result.errors] == [(4, "key"), (5, "params.stale_months")]


def test_a_widget_directive_is_pointed_at_the_bracketed_form():
    result = parse_text("@layout document\n\n@widget context_strategy.summary.figures\n")

    assert "on a line of its own as [[widget.…]]" in result.errors[0].message
    unknown = parse_text("@layout document\n\n@nothing\n").errors[0].message
    assert "widget" not in unknown


def test_a_widget_inside_a_table_block_is_an_error():
    result = parse_text("@layout document\n\n@table requirement\n  [[widget.context_strategy.summary.figures]]\n@end\n")

    assert result.tree is None and "use @column or @end" in result.errors[0].message


def test_a_widget_in_a_table_layout_is_rejected_by_the_validator():
    result = parse_text("@layout table\n\n[[widget.context_strategy.summary.figures]]\n")

    assert not result.ok and "cannot be used in a table layout" in result.errors[0].message


def test_widgets_have_a_block_spec_and_a_text_form():
    assert "widget" in BLOCK_SPECS and "widget" in report_layout_eval._EVALUATORS and TEXT_FORMS["widget"].bracketed


def test_the_text_of_a_hostile_widget_line_is_bounded():
    parse_text("@layout document\n\n[[widget.context_strategy.summary.figures " + "a=1 " * 20_000 + "]]\n")
    parse_text("@layout document\n\n[[widget." + "x" * 100_000 + "]]\n")
    parse_text("@layout document\n\n[[widget.context_strategy.summary.figures since=" + '"' * 20_000 + "]]\n")


# ---- turning a report into blocks -------------------------------------------------------------------------------


def make_result(**kwargs: Any) -> ReportResult:
    from datetime import UTC, datetime

    base: dict[str, Any] = {
        "key": "k", "title": "T", "scope_label": "S", "generated_at": datetime.now(UTC), "notes": [], "sections": [],
    }
    return ReportResult(**{**base, **kwargs})


def part(kind: str, key: str = "a") -> report_widgets.WidgetPart:
    return report_widgets.WidgetPart(key, key, "", kind)


def test_a_table_part_is_the_table_alone_with_no_heading_or_note_of_its_own():
    result = make_result(
        notes=["Covers this project only."], metrics=[("Total", 3)],
        sections=[ReportSection("a", "First", ["X", "Y"], [["1", "2"]], note="About first.", tones=[["info", None]])],
    )

    assert part_blocks(result, part("section", "a")) == [Table(["X", "Y"], [["1", "2"]], compact=True, tones=[["info", None]])]


def test_a_table_with_no_rows_or_a_table_the_report_did_not_produce_is_no_blocks():
    result = make_result(sections=[ReportSection("empty", "Empty", ["X"], [])])

    assert part_blocks(result, part("section", "empty")) == []
    assert part_blocks(result, part("section", "missing")) == []


def test_the_notes_part_is_the_reports_caveats_one_note_each():
    result = make_result(notes=["Covers this project only.", "Scored under the S x F model."])

    assert part_blocks(result, part("notes")) == [Note("Covers this project only."), Note("Scored under the S x F model.")]
    assert part_blocks(make_result(), part("notes")) == []


def test_the_figures_part_is_one_measure_value_table():
    result = make_result(metrics=[("Total", 3), ("Open", "2")])

    assert part_blocks(result, part("figures")) == [Table(["Measure", "Value"], [["Total", "3"], ["Open", "2"]], compact=True)]


def test_grouped_figures_get_a_group_column():
    from app.services.report_framework import ReportMetric

    blocks = part_blocks(make_result(metrics=[ReportMetric("Total", 3, group="Risks"), ReportMetric("Other", 1)]), part("figures"))

    assert blocks == [Table(["Group", "Measure", "Value"], [["Risks", "Total", "3"], ["", "Other", "1"]], compact=True)]


def test_a_result_with_no_figures_has_no_figures_blocks():
    assert part_blocks(make_result(), part("figures")) == []


def test_the_output_digest_changes_with_the_data_and_not_with_the_clock():
    one = make_result(sections=[ReportSection("a", "A", ["X"], [["1"]])])
    again = make_result(sections=[ReportSection("a", "A", ["X"], [["1"]])])
    changed = make_result(sections=[ReportSection("a", "A", ["X"], [["2"]])])

    assert output_digest(one) == output_digest(again) != output_digest(changed)


# ---- running a widget in a layout -------------------------------------------------------------------------------


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Widget Org", context_strategy=True)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


def run(db, world: World, project: dict, tree: dict[str, Any], *, projects: list[dict] | None = None):
    row = db.get(Project, uuid.UUID(project["id"]))
    org = db.get(Organization, uuid.UUID(world.org["id"]))
    scope = [db.get(Project, uuid.UUID(p["id"])) for p in projects] if projects else [row]
    resolver = ArtefactResolver(db, row, world.user_id, include_related=True)
    ctx = ReportContext(module_key="custom_reports", organization=org, projects=scope, root_project=row)
    return evaluate_layout(db, resolver, ctx, tree, title="Report")


def test_a_widget_inserts_only_its_component_and_the_layout_supplies_the_words(db, world):
    project = world.project("Alpha")
    world.pain_point(project, "Slow reports")
    tree = doc({"type": "heading", "text": "Overview"}, widget(SUMMARY), {"type": "text", "text": "After the widget."})

    result = run(db, world, project, tree)

    blocks = result.document.blocks
    assert blocks[0] == Heading("Overview", 1)
    assert isinstance(blocks[1], Table) and blocks[1].columns == ["Group", "Measure", "Value"] and blocks[1].rows
    assert [type(b).__name__ for b in blocks if not isinstance(b, Gap)] == ["Heading", "Table", "Paragraph"]
    assert result.widgets == [SUMMARY]


def test_the_notes_widget_gives_the_reports_caveats_and_nothing_else(db, world):
    project = world.project("Alpha")

    result = run(db, world, project, doc(widget(SUMMARY_NOTES)))

    assert all(isinstance(b, Note) for b in result.document.blocks) and result.document.blocks
    assert result.widgets == [SUMMARY_NOTES]


def test_a_table_widget_matches_the_same_table_of_the_reports_own_run(db, world, client):
    project = world.project("Alpha")
    world.pain_point(project, "Slow reports")
    own = client.get(
        f"/api/v1/projects/{project['id']}/modules/context_strategy/reports/pain-point-coverage",
        headers=auth_headers(world.token),
    )
    assert own.status_code == 200, own.text
    expected = next(sec for sec in own.json()["sections"] if sec["key"] == "matrix")
    assert expected["rows"], "the report has something to show"

    result = run(db, world, project, doc(widget(COVERAGE_MATRIX)))

    (table,) = (b for b in result.document.blocks if isinstance(b, Table))
    assert table.columns == expected["columns"] and table.rows == expected["rows"]


def test_an_empty_component_shows_the_blocks_empty_text_or_nothing(db, world):
    project = world.project("Alpha")  # no Pain Points, so no accepted one lacks a Requirement
    key = "context_strategy.pain-point-coverage.uncovered"

    said = run(db, world, project, doc({"type": "widget", "key": key, "empty_text": "None found in {{project_name}}."}))
    silent = run(db, world, project, doc(widget(key)))

    assert [b.text for b in said.document.blocks] == ["None found in Alpha."]
    assert silent.document.blocks == []
    assert silent.widgets == [key]  # it ran; it simply had nothing to show


def test_the_components_of_one_report_share_one_run_and_different_settings_run_again(db, world, monkeypatch):
    project = world.project("Alpha")
    calls: list[dict[str, Any]] = []
    original = report_widget_run.collect_widget

    def counting(db_, widget_, ctx):
        calls.append(dict(ctx.params))
        return original(db_, widget_, ctx)

    monkeypatch.setattr(report_layout_eval, "collect_widget", counting)
    tree = doc(
        widget("context_strategy.pain-point-coverage.matrix"), widget("context_strategy.pain-point-coverage.uncovered"),
        widget("context_strategy.pain-point-coverage.notes"), widget("context_strategy.pain-point-coverage.matrix"),
        widget(SUMMARY), widget(SUMMARY_NOTES), widget(SUMMARY, stale_months=3),
    )

    result = run(db, world, project, tree)

    assert len(calls) == 3  # coverage once, summary with its defaults once, summary with stale_months=3 once
    assert result.widgets == sorted({
        "context_strategy.pain-point-coverage.matrix", "context_strategy.pain-point-coverage.uncovered",
        "context_strategy.pain-point-coverage.notes", SUMMARY, SUMMARY_NOTES,
    })


def test_parameters_reach_the_collector_typed(db, world, monkeypatch):
    project = world.project("Alpha")
    seen: dict[str, Any] = {}
    original = report_widget_run.collect_widget

    def spy(db_, widget_, ctx):
        seen.update(ctx.params, module=ctx.module_key, root=ctx.root_project.name, projects=[p.name for p in ctx.projects])
        return original(db_, widget_, ctx)

    monkeypatch.setattr(report_layout_eval, "collect_widget", spy)

    run(db, world, project, doc(widget(SUMMARY, stale_months=12, since="2026-01-01")))

    assert seen["stale_months"] == 12 and seen["since"] == date(2026, 1, 1)
    assert seen["rollup"] == "weighted_average"  # the declared default
    assert seen["module"] == "context_strategy" and seen["root"] == "Alpha" and seen["projects"] == ["Alpha"]


def test_a_module_that_is_off_for_the_project_leaves_a_note_not_an_error(db, world):
    project = world.project("Alpha")  # risk_management is not enabled for this organisation

    result = run(db, world, project, doc(widget(RISKS), {"type": "text", "text": "Still here."}))

    notes = [b.text for b in result.document.blocks if isinstance(b, Note)]
    assert notes == ['The "Risk register" report is not available in this project.']
    assert any("Still here." in getattr(b, "text", "") for b in result.document.blocks)
    assert result.warnings == ['The "Risk register" report is not available in this project, so it was left out.']
    assert result.widgets == []  # it did not run


def test_a_report_that_rejects_its_settings_leaves_a_note(db, world, monkeypatch):
    project = world.project("Alpha")

    def refuse(db_, widget_, ctx):
        raise HTTPException(400, "That group is not in this project.")

    monkeypatch.setattr(report_layout_eval, "collect_widget", refuse)

    result = run(db, world, project, doc(widget(SUMMARY), {"type": "text", "text": "After."}))

    notes = [b.text for b in result.document.blocks if isinstance(b, Note)]
    title = report_widgets.find_widget(SUMMARY).report_title
    assert notes == [f'The "{title}" report could not be produced: That group is not in this project.']
    assert result.widgets == []
    assert any("could not be produced" in w for w in result.warnings)
    assert any("After." in getattr(b, "text", "") for b in result.document.blocks)


def test_a_bug_in_a_report_is_not_hidden_as_a_note(db, world, monkeypatch):
    project = world.project("Alpha")

    def broken(db_, widget_, ctx):
        raise RuntimeError("collector bug")

    monkeypatch.setattr(report_layout_eval, "collect_widget", broken)

    with pytest.raises(RuntimeError):
        run(db, world, project, doc(widget(SUMMARY)))


def test_the_provenance_digest_covers_what_a_widget_produced(db, world):
    project = world.project("Alpha")
    before = run(db, world, project, doc(widget(SUMMARY)))
    same = run(db, world, project, doc(widget(SUMMARY)))
    world.pain_point(project, "A new pain point")
    db.expire_all()
    after = run(db, world, project, doc(widget(SUMMARY)))
    plain = run(db, world, project, doc({"type": "text", "text": "x"}))

    assert before.source_digest == same.source_digest
    assert after.source_digest != before.source_digest
    assert plain.widgets == []


def test_a_widget_counts_towards_the_output_cap(db, world, monkeypatch):
    project = world.project("Alpha")
    world.pain_point(project, "Slow reports")
    monkeypatch.setattr(report_layout_eval, "MAX_OUTPUT", 1)

    with pytest.raises(report_layout_eval.LayoutLimitError):
        run(db, world, project, doc(widget(SUMMARY)))


# ---- over HTTP --------------------------------------------------------------------------------------------------


def make_layout(world: World, tree: dict[str, Any], name: str, *, project: dict | None = None) -> dict:
    url = f"/api/v1/projects/{project['id']}/report-layouts" if project else f"/api/v1/orgs/{world.org['id']}/report-layouts"
    resp = world.client.post(
        url, json={"name": name, "description": "d", "family": tree["family"], "tree": tree}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_a_layout_with_a_widget_runs_from_the_project_route_and_records_the_widget(world, db):
    project = world.project("Alpha")
    world.pain_point(project, "Slow reports")
    layout = make_layout(world, doc({"type": "heading", "text": "Context"}, widget(SUMMARY)), "With widget", project=project)

    resp = world.client.get(
        f"/api/v1/projects/{project['id']}/custom-reports/{layout['id']}/run", headers=auth_headers(world.token),
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["sections"], "the widget's tables become sections of the on-screen run"
    row = db.scalars(select(GeneratedReport).where(GeneratedReport.layout_id == uuid.UUID(layout["id"]))).one()
    assert row.widgets == [SUMMARY]
    pdf = world.client.get(
        f"/api/v1/projects/{project['id']}/custom-reports/{layout['id']}/run", params={"format": "pdf"}, headers=auth_headers(world.token),
    )
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    docx = world.client.get(
        f"/api/v1/projects/{project['id']}/custom-reports/{layout['id']}/run", params={"format": "docx"}, headers=auth_headers(world.token),
    )
    assert docx.status_code == 200 and docx.content[:2] == b"PK"


def test_an_organisation_layout_runs_its_widget_once_per_project_and_a_project_without_the_module_notes_it(world, db):
    with_module = world.project("Alpha")
    world.pain_point(with_module, "Slow reports")
    layout = make_layout(world, doc(widget(RISKS)), "Org risks")  # risk_management is off for the whole organisation

    resp = world.client.get(
        f"/api/v1/orgs/{world.org['id']}/custom-reports/{layout['id']}/run", headers=auth_headers(world.token),
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert any("not available" in n for n in body["notes"])
    row = db.scalars(select(GeneratedReport).where(GeneratedReport.layout_id == uuid.UUID(layout["id"]))).one()
    assert row.widgets == []


def test_saving_a_layout_with_an_unknown_widget_is_refused_with_its_position(world):
    resp = world.client.post(
        f"/api/v1/orgs/{world.org['id']}/report-layouts",
        json={"name": "Bad", "description": "", "family": "document", "tree": doc(widget("nope.nothing"))},
        headers=auth_headers(world.token),
    )

    assert resp.status_code == 422
    assert resp.json()["detail"]["errors"][0]["path"] == "nodes[0].key"


def test_the_widget_list_offers_only_what_the_organisation_can_use(world):
    org = world.client.get(f"/api/v1/orgs/{world.org['id']}/report-layouts/widgets", headers=auth_headers(world.token))
    project = world.project("Alpha")
    proj = world.client.get(f"/api/v1/projects/{project['id']}/report-layouts/widgets", headers=auth_headers(world.token))

    assert org.status_code == 200 and proj.status_code == 200, (org.text, proj.text)
    org_keys = [w["key"] for w in org.json()]
    assert SUMMARY in org_keys and RISKS not in org_keys
    assert [w["key"] for w in proj.json()] == [k for k in org_keys if k in {w["key"] for w in proj.json()}]
    summary = next(w for w in org.json() if w["key"] == SUMMARY)
    assert summary["title"] and summary["module_name"] and {p["name"] for p in summary["params"]} >= {"stale_months", "since"}
    assert summary["kind"] == "figures" and summary["report_title"] == "Context & Strategy summary"
    register = next(w for w in org.json() if w["key"] == COVERAGE_MATRIX)
    assert register["kind"] == "section" and register["title"] == "Type × status"
    stale = next(p for p in summary["params"] if p["name"] == "stale_months")
    assert stale["type"] == "integer" and stale["minimum"] == 1 and stale["maximum"] == 120 and stale["default"] == 6

    world.enable("risk_management")
    assert RISKS in [w["key"] for w in world.client.get(
        f"/api/v1/orgs/{world.org['id']}/report-layouts/widgets", headers=auth_headers(world.token)).json()]


def test_the_widget_list_needs_the_manage_permission(world, client):
    from tests.conftest import create_org_user, login

    email = f"plain-{uuid.uuid4().hex[:6]}@example.com"
    create_org_user(client, world.token, world.org["id"], email)
    token = login(client, email, "Password123!")
    project = world.project("Alpha")

    for url in (
        f"/api/v1/orgs/{world.org['id']}/report-layouts/widgets", f"/api/v1/projects/{project['id']}/report-layouts/widgets",
    ):
        assert client.get(url, headers=auth_headers(token)).status_code in (403, 404)
        assert client.get(url).status_code in (401, 403)


def test_the_widget_text_view_round_trips_through_the_api(world):
    text = "@layout document\n\n# Heading\n[[widget.context_strategy.summary.figures stale_months=12]]\n"

    parsed = world.client.post(
        f"/api/v1/orgs/{world.org['id']}/report-layouts/text/parse", json={"text": text}, headers=auth_headers(world.token),
    ).json()
    assert parsed["ok"] and parsed["tree"]["nodes"][-1] == widget(SUMMARY, stale_months=12)

    formatted = world.client.post(
        f"/api/v1/orgs/{world.org['id']}/report-layouts/text/format", json={"tree": parsed["tree"]}, headers=auth_headers(world.token),
    ).json()
    assert "[[widget.context_strategy.summary.figures stale_months=12]]" in formatted["text"]
    json.dumps(formatted)


# ---- the declared tables are the tables the collectors produce --------------------------------------------------

#: Reports whose table keys depend on the data and so cannot all be declared: the summary pack re-lists every other
#: report's gap tables, and the risk matrices are named per distinct scoring grid.
DATA_DEPENDENT_KEYS = {"context_strategy.summary": None}
DATA_DEPENDENT_PREFIXES = ("matrix_",)


def test_every_report_declares_the_tables_its_collector_produces(db, client, admin_token):
    world = World(client, admin_token, "Parts Org", decisions=True, context_strategy=True)
    for module in ("stakeholders", "risk_management"):
        world.enable(module)
    project = world.project("Alpha")
    world.pain_point(project, "Slow reports")
    row = db.get(Project, uuid.UUID(project["id"]))
    org = db.get(Organization, uuid.UUID(world.org["id"]))
    problems = []

    for module_key, definition in get_all_reports():
        report_key = f"{module_key}.{definition.slug}"
        if report_key in DATA_DEPENDENT_KEYS:
            continue
        widget_info = next(w for w in report_widgets.list_widgets() if w.report_key == report_key)
        ctx = report_widget_run.widget_context(
            ReportContext(module_key=module_key, organization=org, projects=[row], root_project=row), widget_info,
            report_widgets.typed_params(widget_info, None),
        )
        produced = {
            sec.key for sec in report_widget_run.collect_widget(db, widget_info, ctx).sections
            if not sec.key.startswith(DATA_DEPENDENT_PREFIXES)
        }
        declared = {p.key for p in definition.parts}
        if produced - declared:
            problems.append(f"{report_key}: produces undeclared tables {sorted(produced - declared)}")
        if declared - produced:
            problems.append(f"{report_key}: declares tables the collector did not produce {sorted(declared - produced)}")

    assert not problems, "\n".join(problems)
