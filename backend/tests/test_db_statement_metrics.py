"""Tests for the `db_statements_total` Prometheus counter (platform enhancements
plan, Phase 3): each executed statement is counted by operation only, and the
unauthenticated `/metrics` output never carries table names, ids or SQL."""

import re

import pytest
from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.sql import column, table

from app.metrics import DB_OPERATIONS, classify_statement
from tests.conftest import auth_headers, create_project

_SAMPLE = re.compile(r'^db_statements_total\{operation="(?P<op>[^"]+)"\} (?P<value>[0-9.e+]+)$', re.MULTILINE)


def _counts(client) -> dict[str, float]:
    """Parses `db_statements_total` per operation out of the `/metrics` text."""
    return {m["op"]: float(m["value"]) for m in _SAMPLE.finditer(client.get("/metrics").text)}


def test_every_operation_series_exists_from_the_start(client):
    assert set(_counts(client)) == set(DB_OPERATIONS)


def test_read_request_increments_select_only(client, admin_token):
    before = _counts(client)
    assert client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).status_code == 200
    after = _counts(client)
    assert after["select"] > before["select"]
    assert after["insert"] == before["insert"]
    assert after["delete"] == before["delete"]


def test_create_request_increments_insert(client, admin_token, org_id):
    before = _counts(client)
    create_project(client, admin_token, org_id, "DB metrics project")
    assert _counts(client)["insert"] > before["insert"]


def test_labels_are_operation_only_and_leak_no_names_or_sql(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "DB metrics leak check")
    text_out = client.get("/metrics").text
    db_lines = [line for line in text_out.splitlines() if line.startswith("db_statements_total")]
    assert db_lines
    for line in db_lines:
        assert re.match(r'^db_statements_total\{operation="(select|insert|update|delete|other)"\} ', line)
    assert project["id"] not in text_out
    assert "projects" not in "".join(db_lines)


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        (select(column("a")).select_from(table("t")), "select"),
        (select(column("a")).select_from(table("t")).with_for_update(), "select"),
        (insert(table("t", column("a"))).values(a=1), "insert"),
        (update(table("t", column("a"))).values(a=1), "update"),
        (delete(table("t")), "delete"),
        (text("SELECT 1"), "other"),
        (None, "other"),
    ],
)
def test_classify_statement(statement, expected):
    assert classify_statement(statement) == expected


def test_cte_insert_counts_as_insert_not_select():
    t = table("t", column("a"))
    cte = select(column("a")).select_from(table("s")).cte("src")
    assert classify_statement(insert(t).from_select(["a"], select(cte.c.a))) == "insert"
