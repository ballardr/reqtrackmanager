"""Tests for the vocabulary migration (`migrations/0172_architecture_vocabularies.py`): downgrading drops both tables and
upgrading recreates them and backfills the default types for an organisation that already exists, without doubling the
types an organisation was already given. A second test covers the record tables of `0173_architecture_records.py`.
Runs the real migrations and always upgrades back to head."""

from __future__ import annotations

import uuid

from sqlalchemy import text

from alembic import command
from app.database import engine
from app.modules.architecture.service import DEFAULT_ELEMENT_TYPES
from tests.conftest import build_alembic_config, create_org_admin_in

#: The flat connection types the vocabulary migration backfills for an existing organisation; the groups a new
#: organisation is seeded with (`DEFAULT_CONNECTION_TYPES`) are not added to an existing one.
_BACKFILLED_CONNECTION_TYPES = 14


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
    assert _count("architecture_connection_types", org["id"]) == _BACKFILLED_CONNECTION_TYPES
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


def test_the_sharing_migration_adds_the_owner_column_and_the_collection_tables_and_reverses_cleanly(client, admin_token):
    """Downgrading 0174 removes the collection tables, the organisation owner column and organisation-owned elements;
    upgrading restores the shape. Project-owned elements survive both ways."""
    from app.modules.architecture.tests._helpers import make_element, make_org_element, setup

    org, project, token = setup(client, admin_token, "Arch sharing migration")
    kept = make_element(client, token, project["id"], "Kept")
    make_org_element(client, token, org["id"], "Dropped")
    command.downgrade(build_alembic_config(), "0173")
    try:
        for table in ("architecture_collections", "architecture_collection_members", "architecture_collection_grants"):
            assert not _table_exists(table)
        with engine.connect() as conn:
            columns = {r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'architecture_elements'"
            ))}
            remaining = {str(r[0]) for r in conn.execute(text("SELECT id FROM architecture_elements"))}
        assert "organization_id" not in columns and kept["id"] in remaining
    finally:
        command.upgrade(build_alembic_config(), "head")
    for table in ("architecture_collections", "architecture_collection_members", "architecture_collection_grants"):
        assert _table_exists(table)
    with engine.connect() as conn:
        assert conn.execute(text(
            "SELECT is_nullable FROM information_schema.columns WHERE table_name = 'architecture_elements' AND column_name = 'project_id'"
        )).scalar_one() == "YES"


def test_the_symbols_migration_adds_the_table_and_columns_backfills_builtins_and_reverses_cleanly(client, admin_token):
    """Downgrading 0175 removes the symbol table and the `symbol_id` columns, leaving the types and elements; upgrading
    recreates them and gives an organisation that already exists the built-in symbols (rows only), changing no type."""
    from app.modules.architecture.service import DEFAULT_SYMBOLS
    from app.modules.architecture.tests._helpers import make_element, setup

    org, project, token = setup(client, admin_token, "Arch symbols migration")
    kept = make_element(client, token, project["id"], "Kept")
    command.downgrade(build_alembic_config(), "0174")
    try:
        assert not _table_exists("architecture_symbols")
        with engine.connect() as conn:
            columns = {
                (r[0], r[1]) for r in conn.execute(text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_name IN ('architecture_elements', 'architecture_element_types')"
                ))
            }
            remaining = {str(r[0]) for r in conn.execute(text("SELECT id FROM architecture_elements"))}
        assert ("architecture_elements", "symbol_id") not in columns and ("architecture_element_types", "symbol_id") not in columns
        assert kept["id"] in remaining
    finally:
        command.upgrade(build_alembic_config(), "head")
    assert _table_exists("architecture_symbols")
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name, builtin_key, file_asset_id FROM architecture_symbols WHERE organization_id = :o ORDER BY sort_order"),
            {"o": uuid.UUID(org["id"])},
        ).all()
        assigned = conn.execute(text(
            "SELECT count(*) FROM architecture_element_types WHERE organization_id = :o AND symbol_id IS NOT NULL"
        ), {"o": uuid.UUID(org["id"])}).scalar_one()
    assert [(r[1], r[0]) for r in rows] == [(key, name) for key, name in DEFAULT_SYMBOLS]
    assert all(r[2] is None for r in rows) and assigned == 0


def test_the_diagrams_migration_adds_the_tables_and_reverses_cleanly(client, admin_token):
    """Downgrading 0176 drops the five diagram tables and leaves the elements they placed; upgrading recreates them
    empty (nothing is seeded)."""
    from app.modules.architecture.tests._helpers import make_diagram, make_element, place, setup

    _org, project, token = setup(client, admin_token, "Arch diagrams migration")
    kept = make_element(client, token, project["id"], "Kept")
    place(client, token, project["id"], make_diagram(client, token, project["id"], "Context"), kept["id"])
    tables = (
        "architecture_diagrams", "architecture_diagram_placements", "architecture_diagram_notes",
        "architecture_diagram_toggles", "architecture_diagram_toggle_members",
    )
    command.downgrade(build_alembic_config(), "0175")
    try:
        assert not any(_table_exists(t) for t in tables)
        with engine.connect() as conn:
            remaining = {str(r[0]) for r in conn.execute(text("SELECT id FROM architecture_elements"))}
        assert kept["id"] in remaining
    finally:
        command.upgrade(build_alembic_config(), "head")
    assert all(_table_exists(t) for t in tables)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM architecture_diagrams")).scalar_one() == 0


def test_the_type_tree_migration_adds_the_link_table_and_reverses_cleanly(client, admin_token):
    """Downgrading 0177 drops the parent link table and leaves the connection types; upgrading recreates it empty
    (nothing is seeded, so an existing organisation's flat list is unchanged)."""
    from app.modules.architecture.tests._helpers import setup

    org, _project, _token = setup(client, admin_token, "Arch tree migration")
    before = _count("architecture_connection_types", org["id"])
    command.downgrade(build_alembic_config(), "0176")
    try:
        assert not _table_exists("architecture_connection_type_parents")
        assert _count("architecture_connection_types", org["id"]) == before
    finally:
        command.upgrade(build_alembic_config(), "head")
    assert _table_exists("architecture_connection_type_parents")
    assert _count("architecture_connection_types", org["id"]) == before
    with engine.connect() as conn:
        # The seeded organisation's links are gone with the table; the types keep their rows and no row is invented.
        assert conn.execute(text("SELECT count(*) FROM architecture_connection_type_parents")).scalar_one() == 0
