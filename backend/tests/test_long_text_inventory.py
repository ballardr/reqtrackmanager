"""
Module: tests.test_long_text_inventory

Pins the long-text inventory: every long free-text column is declared Markdown or plain text with a reason (so a column
added later cannot be missed, as a new record type cannot miss search), the declarations agree with the search
declarations and the write-time limits refuse what the declarations bound.
"""

import importlib.util
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, make_transient_to_detached
from sqlalchemy.orm.attributes import InstrumentedAttribute, set_committed_value

from app import main as application
from app.database import SessionLocal
from app.models.record_comment import RecordComment
from app.models.requirement import RequirementVersion
from app.modules.registry import get_markdown_fields, get_plain_text_fields, get_search_providers
from app.services import markdown_fields


def test_the_application_installs_the_write_limit_hook() -> None:
    assert application.app is not None
    assert event.contains(Session, "before_flush", markdown_fields._before_flush)


ROOT = Path(__file__).resolve().parents[2]


def _generator():
    script = ROOT / "backend" / "scripts" / "generate_long_text_inventory.py"
    spec = importlib.util.spec_from_file_location("generate_long_text_inventory", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_long_text_column_is_markdown_or_says_why_not() -> None:
    markdown = markdown_fields.declared_columns()
    plain = get_plain_text_fields()
    columns = set(_generator().long_text_columns())
    undeclared = sorted(columns - markdown.keys() - plain.keys())
    assert undeclared == [], (
        f"long-text columns with no declaration (add a MarkdownField, or a reason in plain_text_fields): {undeclared}"
    )
    assert sorted(markdown.keys() & plain.keys()) == [], "a column is declared both Markdown and plain text"
    assert sorted(plain.keys() - columns) == [], "a plain-text declaration names a column that is not long text"
    assert sorted(markdown.keys() - columns) == [], "a Markdown declaration names a column that is not long text"
    assert all(reason.strip() for reason in plain.values()), "a plain-text column needs a reason"


def test_declared_limits_are_positive_and_math_only_where_equations_are_written() -> None:
    fields = markdown_fields.declared_columns()
    assert all(f.limit > 0 for f in fields.values())
    assert sorted(key for key, f in fields.items() if f.math) == [
        "change_request_versions.proposed_clarification",
        "change_request_versions.proposed_description",
        "change_request_versions.proposed_reasoning",
        "requirement_versions.clarification",
        "requirement_versions.description",
        "requirement_versions.reasoning",
    ]


def test_search_fields_flag_markdown_exactly_when_the_column_is_declared_markdown() -> None:
    declared = markdown_fields.declared_columns()
    problems = []
    for artefact_type, provider in get_search_providers().items():
        for search_field in provider.fields:
            column = search_field.column
            if not isinstance(column, InstrumentedAttribute):
                continue
            physical = column.property.columns[0]
            key = f"{physical.table.name}.{physical.name}"
            if key not in declared and key.split(".")[1] not in ("name", "title"):
                # a short column (a name, a status) is neither
                if search_field.markdown:
                    problems.append(f"{artefact_type}.{search_field.key} is flagged Markdown but {key} is not declared")
            elif key in declared and not search_field.markdown:
                problems.append(f"{artefact_type}.{search_field.key} reads Markdown {key} without markdown=True")
    assert problems == []


def test_a_declared_field_over_its_limit_is_refused_on_flush() -> None:
    db = SessionLocal()
    try:
        db.add(RecordComment(body="x" * 20_001))
        with pytest.raises(HTTPException) as caught:
            db.flush()
        assert caught.value.status_code == 422
        assert "Body" in str(caught.value.detail)
    finally:
        db.rollback()
        db.close()


def test_a_diagram_heavy_field_is_refused_on_flush() -> None:
    db = SessionLocal()
    try:
        db.add(RequirementVersion(requirement_id=uuid.uuid4(), description="```mermaid\ngraph TD; A-->B\n```\n" * 25))
        with pytest.raises(HTTPException) as caught:
            db.flush()
        assert caught.value.status_code == 422
    finally:
        db.rollback()
        db.close()


def test_a_stored_value_over_the_limit_is_refused_only_when_that_field_is_edited() -> None:
    comment = RecordComment(id=uuid.uuid4())
    set_committed_value(comment, "body", "y" * 30_000)
    make_transient_to_detached(comment)
    declared = markdown_fields._classes()[RecordComment]
    markdown_fields.check_instance(comment, declared, only_changed=True)
    assert not inspect(comment).attrs.body.history.has_changes()
    comment.body = "y" * 30_001
    with pytest.raises(HTTPException):
        markdown_fields.check_instance(comment, declared, only_changed=True)


def test_every_declaration_resolves_to_a_mapped_class() -> None:
    assert all(isinstance(f.column, InstrumentedAttribute) for f in get_markdown_fields())
