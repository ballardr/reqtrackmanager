"""Tests for the vocabulary migration (`migrations/0172_architecture_vocabularies.py`): downgrading drops both tables and
upgrading recreates them and backfills the default types for an organisation that already exists, without doubling the
types an organisation was already given. A second test covers the record tables of `0173_architecture_records.py`.
Runs the real migrations and always upgrades back to head."""

from __future__ import annotations

import uuid

from sqlalchemy import text

from alembic import command
from app.database import engine
from app.modules.architecture.service import DEFAULT_CONNECTION_TYPES, DEFAULT_ELEMENT_TYPES
from tests.conftest import build_alembic_config, create_org_admin_in


def _count(table: str, org_id: str) -> int:
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {table} WHERE organization_id = :o"), {"o": uuid.UUID(org_id)}).scalar_one()


def _table_exists(table: str) -> bool:
    with engine.connect() as conn:
        return conn.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar_one() is not None


def test_downgrade_drops_the_tables_and_upgrade_backfills_existing_organisations(client, admin_token):
    org, _token = create_org_admin_in(client, admin_token, "Arch migration org")
    assert _count("architecture_element_types", org["id"]) == len(DEFAULT_ELEMENT_TYPES)

    command.downgrade(build_alembic_config(), "0171")
    try:
        assert not _table_exists("architecture_element_types")
        assert not _table_exists("architecture_connection_types")
    finally:
        command.upgrade(build_alembic_config(), "head")

    assert _count("architecture_element_types", org["id"]) == len(DEFAULT_ELEMENT_TYPES)
    assert _count("architecture_connection_types", org["id"]) == len(DEFAULT_CONNECTION_TYPES)
    with engine.connect() as conn:
        names = [r[0] for r in conn.execute(
            text("SELECT name FROM architecture_element_types WHERE organization_id = :o ORDER BY sort_order"),
            {"o": uuid.UUID(org["id"])},
        )]
    assert names == [d[0] for d in DEFAULT_ELEMENT_TYPES]


def test_upgrading_twice_does_not_double_the_backfill(client, admin_token):
    org, _token = create_org_admin_in(client, admin_token, "Arch migration twice")
    command.downgrade(build_alembic_config(), "0171")
    command.upgrade(build_alembic_config(), "head")
    command.downgrade(build_alembic_config(), "0171")
    command.upgrade(build_alembic_config(), "head")
    assert _count("architecture_element_types", org["id"]) == len(DEFAULT_ELEMENT_TYPES)


def test_the_records_migration_drops_and_recreates_the_record_tables_leaving_the_vocabularies(client, admin_token):
    """Downgrading 0173 removes elements, ports and connections only; upgrading recreates them empty."""
    org, _token = create_org_admin_in(client, admin_token, "Arch records migration")
    command.downgrade(build_alembic_config(), "0172")
    try:
        for table in ("architecture_elements", "architecture_ports", "architecture_connections"):
            assert not _table_exists(table)
        assert _table_exists("architecture_element_types") and _table_exists("architecture_connection_types")
    finally:
        command.upgrade(build_alembic_config(), "head")
    for table in ("architecture_elements", "architecture_ports", "architecture_connections"):
        assert _table_exists(table)
    assert _count("architecture_element_types", org["id"]) == len(DEFAULT_ELEMENT_TYPES)
