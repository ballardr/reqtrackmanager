"""Tests for how a report orders the records it lists (`ReportContext.order_records`, `ReportDefinition.record_order`):
by code or by title ascending, never by whatever a list on screen was sorted to, and a collector never orders a list
of records by code, title or name by itself.

A table that is a ranking on purpose (highest score first, longest overdue first, a log oldest first) orders itself;
the collector marks that line `# ranked: <why>`. A sort over names inside one cell or a fixed structure order is marked
`# not-a-list: <why>`; the core requirements report, which has no `ReportContext`, orders by `natural_key` and is marked
`# code order:`.
The scan reads every report collector's source, so a new report that sorts its records by hand fails here.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

from app.models.organization import Organization
from app.modules.registry import ReportDefinition
from app.services.report_framework import ReportContext

BACKEND = Path(__file__).resolve().parents[1] / "app"
MARKERS = ("# ranked:", "# not-a-list:", "# code order:")
#: What makes a sort a record ordering: it mentions a record's code, title or name.
RECORD_KEYS = ("unique_code", ".name", ".title", ".lower()", "casefold")


def _collector_files() -> list[Path]:
    files = sorted((BACKEND / "modules").glob("*/reports*.py"))
    files.append(BACKEND / "routers" / "reports.py")
    return files


def _ordering_calls(tree: ast.AST):
    """Every `sorted(...)`, `x.sort(...)` and `.order_by(...)` call in `tree`."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Name) and func.id == "sorted") or (isinstance(func, ast.Attribute) and func.attr in ("sort", "order_by")):
            yield node


def test_a_report_collector_never_orders_its_records_by_code_or_title_itself():
    problems: list[str] = []
    for path in _collector_files():
        source = path.read_text()
        lines = source.splitlines()
        for call in _ordering_calls(ast.parse(source)):
            segment = ast.get_source_segment(source, call) or ""
            if not any(key in segment for key in RECORD_KEYS):
                continue
            span = "\n".join(lines[call.lineno - 1:(call.end_lineno or call.lineno)])
            if any(marker in span for marker in MARKERS) or any(marker in lines[call.lineno - 2] for marker in MARKERS if call.lineno > 1):
                continue
            problems.append(f"{path.relative_to(BACKEND.parent)}:{call.lineno}: {segment.splitlines()[0].strip()[:90]}")
    assert not problems, (
        "order a list of records with `ctx.order_records(...)`, or mark a deliberate ranking `# ranked: <why>`:\n" + "\n".join(problems)
    )


class _Item:
    def __init__(self, code: str, title: str, project: str = "A") -> None:
        self.code, self.title, self.project = code, title, project


def _context(order: str = "code") -> ReportContext:
    organization = Organization(id=uuid.uuid4(), name="O", code="O")
    return ReportContext(module_key="m", organization=organization, projects=[], record_order=order)  # type: ignore[arg-type]


def test_records_are_ordered_by_code_with_numbers_by_value_by_default():
    items = [_Item("REQ-10", "b"), _Item("req-2", "c"), _Item("REQ-1", "a")]
    ordered = _context().order_records(items, code=lambda i: i.code, title=lambda i: i.title)
    assert [i.code for i in ordered] == ["REQ-1", "req-2", "REQ-10"]


def test_a_report_that_orders_by_title_does_so_ascending_and_ties_break_by_code():
    items = [_Item("REQ-3", "Beta"), _Item("REQ-2", "alpha"), _Item("REQ-1", "Beta")]
    ordered = _context("title").order_records(items, code=lambda i: i.code, title=lambda i: i.title)
    assert [i.code for i in ordered] == ["REQ-2", "REQ-1", "REQ-3"]


def test_groups_are_the_reports_own_order_and_records_are_ordered_inside_each():
    items = [_Item("REQ-1", "a", "Zeta"), _Item("REQ-2", "b", "Alpha"), _Item("REQ-3", "c", "Zeta"), _Item("REQ-10", "d", "Alpha")]
    ordered = _context().order_records(items, code=lambda i: i.code, title=lambda i: i.title, group=lambda i: i.project)
    assert [i.code for i in ordered] == ["REQ-2", "REQ-10", "REQ-1", "REQ-3"]


def test_a_report_definition_declares_how_it_orders_records_and_defaults_to_code():
    definition = ReportDefinition(key="r", slug="r", title="t", description="d", collector=lambda db, ctx: None)  # type: ignore[arg-type,return-value]
    assert definition.record_order == "code"
