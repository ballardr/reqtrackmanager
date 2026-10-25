"""Tests for the performance dataset generator (`app/services/perf_dataset`).

Covered: the profiles file validates and scales as stated, a spec is deterministic and keyed so a snapshot is
never reused for a different one, the generator refuses to run outside the performance stack, a generated dataset
is consistent (codes, counters, versions, links), it populates every column the application's own create path
populates (the drift guard), and every registered artefact type has a generator, a stated reason, or a place on
the tracked-gap list (which may only shrink).
"""

from __future__ import annotations

import random
import uuid
from pathlib import Path

import pytest
import yaml
from sqlalchemy import func, select, text

from app.database import SessionLocal
from app.models.project import Project
from app.models.requirement import Requirement
from app.modules.registry import get_all_registered_artefact_types, get_no_perf_generator_types, get_perf_generators
from app.services.perf_dataset import textgen
from app.services.perf_dataset.build import RefusedToRun, check_integrity, generate_dataset, require_perf_stack
from app.services.perf_dataset.context import insert_rows, uuid_from
from app.services.perf_dataset.spec import ProfileError, build_spec
from tests.conftest import auth_headers, create_component_and_category, create_project

_PROFILES_FILE = Path(__file__).resolve().parents[2] / "perf" / "datasets" / "profiles.yaml"

#: Registered artefact types whose generator is still to be written. Shrinks only: a type that gains a generator
#: (or a reason) must be removed from this set, and a new type must ship with one of the three.
TRACKED_GAPS = frozenset(
    {
        "change_request",
        "compliance_evidence",
        "compliance_required_action_assessment",
        "compliance_requirement",
        "decision",
        "engagement",
        "future_state",
        "guiding_principle",
        "open_question",
        "pain_point",
        "persona",
        "project_compliance_requirement",
        "research_finding",
        "risk",
        "stakeholder",
        "stakeholder_group",
        "stakeholder_need",
        "strategy",
    }
)

SMALL = {
    "version": 1,
    "tiers": {"T0": 30, "T1": 100},
    "ratios": {"actions": 0.3, "comments": 1.5, "tags_per_requirement": 1.2, "versions_per_requirement": 2.0, "tag_vocabulary": 8},
    "link_density": {"sparse": {"mean_degree": 1}, "typical": {"mean_degree": 3}},
    "hub_exponent": 0.6,
    "cross_level_link_fraction": 0.1,
    "users_per_org": 3,
    "breadth": {
        "single": {"organisations": 1, "projects_per_org": 1},
        "two": {"organisations": 1, "projects_per_org": 2},
        "nested": {"organisations": 1, "nesting": {"depth": 2, "fanout": 2}},
    },
}


needs_profiles = pytest.mark.skipif(not _PROFILES_FILE.is_file(), reason="perf/ is not available in this environment")


def _profiles() -> dict:
    return yaml.safe_load(_PROFILES_FILE.read_text())


# --- the profiles file and the spec ----------------------------------------------------------------------


@needs_profiles
def test_shipped_profiles_build_every_combination():
    profiles = _profiles()
    for tier in profiles["tiers"]:
        for breadth in profiles["breadth"]:
            for density in profiles["link_density"]:
                spec = build_spec(profiles, tier=tier, breadth=breadth, density=density)
                assert spec.requirements_per_project == profiles["tiers"][tier]
                assert spec.total_requirements == spec.total_projects * spec.requirements_per_project


@needs_profiles
def test_shipped_tiers_match_the_documented_sizes():
    assert _profiles()["tiers"] == {"T0": 30, "T1": 100, "T2": 1000, "T3": 5000, "T4": 20000}


@needs_profiles
def test_nested_profile_counts_every_level():
    spec = build_spec(_profiles(), tier="T0", breadth="nested-3x5")
    assert spec.topology.projects_in_org == 1 + 5 + 25


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"tier": "T9"}, "unknown tier"),
        ({"tier": "T0", "breadth": "x"}, "unknown breadth"),
        ({"tier": "T0", "density": "x"}, "unknown link density"),
        ({"tier": "T0", "seed": "1"}, "seed"),
    ],
)
@needs_profiles
def test_build_spec_rejects_unknown_names(kwargs, message):
    with pytest.raises(ProfileError, match=message):
        build_spec(_profiles(), **kwargs)


@needs_profiles
def test_build_spec_rejects_a_missing_section_and_a_bad_number():
    profiles = _profiles()
    del profiles["ratios"]
    with pytest.raises(ProfileError, match="missing section"):
        build_spec(profiles, tier="T0")
    profiles = _profiles()
    profiles["ratios"]["actions"] = -1
    with pytest.raises(ProfileError, match="ratios.actions"):
        build_spec(profiles, tier="T0")


@needs_profiles
def test_snapshot_key_changes_with_every_input_that_changes_the_data():
    profiles = _profiles()
    base = build_spec(profiles, tier="T1").snapshot_key("rev1")
    assert build_spec(profiles, tier="T1").snapshot_key("rev1") == base
    assert build_spec(profiles, tier="T2").snapshot_key("rev1") != base
    assert build_spec(profiles, tier="T1", seed=2).snapshot_key("rev1") != base
    assert build_spec(profiles, tier="T1", density="dense").snapshot_key("rev1") != base
    assert build_spec(profiles, tier="T1").snapshot_key("rev2") != base
    changed = _profiles()
    changed["ratios"]["comments"] = 9
    assert build_spec(changed, tier="T1").snapshot_key("rev1") != base


def test_text_and_ids_are_deterministic_and_varied():
    a, b = random.Random("x"), random.Random("x")
    assert [textgen.title(a) for _ in range(5)] == [textgen.title(b) for _ in range(5)]
    assert uuid_from(random.Random(1)) == uuid_from(random.Random(1))
    assert uuid_from(random.Random(1)).version == 4
    lengths = {len(textgen.paragraphs(random.Random(i), empty_chance=0.2, long_chance=0.2)) for i in range(60)}
    assert 0 in lengths and max(lengths) > 400  # empty through multi-paragraph


def test_generator_refuses_outside_the_performance_stack(monkeypatch):
    monkeypatch.delenv("PERF_STACK", raising=False)
    with pytest.raises(RefusedToRun):
        require_perf_stack()
    monkeypatch.setenv("PERF_STACK", "1")
    require_perf_stack()


# --- generating a dataset --------------------------------------------------------------------------------


def _reset(client) -> None:
    """Empties the database and recreates the server administrator: a dataset is generated once per database."""
    from app.database import Base
    from app.database import engine as app_engine
    from app.services.bootstrap import run_bootstrap

    with app_engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE " + ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables) + " CASCADE"))
    db = SessionLocal()
    try:
        run_bootstrap(db)
    finally:
        db.close()


def _generate(client, breadth: str, *, density: str = "typical", seed: int = 1) -> dict:
    spec = build_spec(SMALL, tier="T0", breadth=breadth, density=density, seed=seed)
    db = SessionLocal()
    try:
        return generate_dataset(
            db,
            client,
            spec,
            admin_email="admin@example.com",
            admin_password="ChangeMe123!",
            user_password="Password123!",
            say=lambda _line: None,
            enforce_guard=False,
        )
    finally:
        db.close()


def test_generated_dataset_is_consistent_and_sized(client):
    manifest = _generate(client, "two")
    assert manifest["integrity_problems"] == []
    assert manifest["spec"]["total_requirements"] == 60
    rows = manifest["rows"]
    assert rows["requirements"] == 60
    assert rows["requirement_versions"] >= 60  # at least one version each, more where edited
    assert rows["requirement_actions"] == 2 * round(30 * 0.3)
    assert rows["audit_events"] > rows["requirements"]
    assert rows["review_comments"] == 2 * round(30 * 1.5)
    assert manifest["link_degree_histogram"]["links"] > 0
    db = SessionLocal()
    try:
        counters = db.execute(select(Project.next_requirement_seq, Project.next_action_seq).where(Project.name.like("Perf Project%"))).all()
        assert counters and all(c[0] == 31 for c in counters)
        codes = db.scalars(select(Requirement.unique_code).order_by(Requirement.unique_code)).all()
        assert len(codes) == len(set((c, i) for i, c in enumerate(codes)))
    finally:
        db.close()


def test_the_generated_people_can_sign_in_and_read_what_was_generated(client):
    manifest = _generate(client, "single")
    org = manifest["organisations"][0]
    token = client.post("/api/v1/auth/login", json={"email": org["member_emails"][0], "password": "Password123!"}).json()["access_token"]
    project_id = manifest["projects"][0]["id"]
    listed = client.get(f"/api/v1/projects/{project_id}/requirements", headers=auth_headers(token))
    assert listed.status_code == 200
    assert 0 < len(listed.json()) <= 30  # archived requirements are hidden by default


def test_nested_profile_links_a_child_to_its_parent(client):
    manifest = _generate(client, "nested")
    assert len(manifest["projects"]) == 3
    assert manifest["integrity_problems"] == []
    assert manifest["link_degree_histogram"].get("cross_level_links", 0) > 0
    db = SessionLocal()
    try:
        cross = db.scalar(text("SELECT count(*) FROM artefact_links WHERE source_project_id IS NOT NULL AND target_project_id IS NOT NULL"))
        assert cross == manifest["link_degree_histogram"]["cross_level_links"]
    finally:
        db.close()


def test_same_spec_produces_the_same_shape(client):
    first = _generate(client, "single", seed=7)
    _reset(client)
    second = _generate(client, "single", seed=7)
    assert first["rows"] == second["rows"]
    assert first["link_degree_histogram"] == second["link_degree_histogram"]
    _reset(client)
    different = _generate(client, "single", seed=8)
    assert different["rows"] != first["rows"] or different["link_degree_histogram"] != first["link_degree_histogram"]


def test_density_scales_the_number_of_links(client):
    sparse = _generate(client, "single", density="sparse")["link_degree_histogram"]["links"]
    _reset(client)
    typical = _generate(client, "single", density="typical")["link_degree_histogram"]["links"]
    assert typical > sparse * 2


@needs_profiles
def test_link_degree_has_a_heavy_tail():
    profiles = _profiles()
    spec = build_spec(profiles, tier="T3", density="typical")
    from app.services.perf_dataset.core import _zipf_cumulative

    n = spec.requirements_per_project
    rng = random.Random(3)
    cumulative = _zipf_cumulative(rng, n, spec.ratios.hub_exponent)
    degree = [0] * n
    for a, b in zip(rng.choices(range(n), cum_weights=cumulative, k=n * 3), rng.choices(range(n), cum_weights=cumulative, k=n * 3), strict=False):
        degree[a] += 1
        degree[b] += 1
    mean = sum(degree) / n
    assert 5 < mean < 7  # two endpoints per link, mean degree 3 per direction
    assert max(degree) > 20 * mean  # a few hubs hold hundreds


def test_check_integrity_flags_a_broken_dataset(client):
    manifest = _generate(client, "single")
    project_id = uuid.UUID(manifest["projects"][0]["id"])
    db = SessionLocal()
    try:
        db.execute(
            text(
                "UPDATE requirement_versions SET valid_to = now() WHERE valid_to IS NULL "
                "AND requirement_id = (SELECT id FROM requirements WHERE project_id = :p LIMIT 1)"
            ),
            {"p": project_id},
        )
        db.execute(text("UPDATE projects SET next_requirement_seq = 1 WHERE id = :p"), {"p": project_id})
        db.commit()
        problems = check_integrity(db, [project_id])
        assert any("no current version" in p for p in problems)
        assert any("next_requirement_seq" in p for p in problems)
        assert check_integrity(db, []) == ["no projects were generated"]
    finally:
        db.close()


def test_insert_rows_chunks_and_counts(client):
    manifest = _generate(client, "single")
    db = SessionLocal()
    try:
        from app.models.tag import Tag

        project = uuid.UUID(manifest["projects"][0]["id"])
        org = uuid.UUID(manifest["projects"][0]["organization_id"])
        rows = [
            {
                "id": uuid.uuid4(),
                "organization_id": org,
                "project_id": project,
                "name": f"t{i}",
                "name_key": f"t{i}",
                "colour": None,
                "created_by": None,
            }
            for i in range(7)
        ]
        assert insert_rows(db, Tag, rows, chunk=3) == 7
        assert insert_rows(db, Tag, [], chunk=3) == 0
    finally:
        db.rollback()
        db.close()


# --- drift guard: the generator populates what the application populates --------------------------------


def _populated_columns(db, table: str, where: str, params: dict) -> set[str]:
    """Columns of `table` that are non-null in at least one row matching `where`."""
    columns = [r[0] for r in db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"), {"t": table})]
    select_list = ", ".join(f'bool_or("{c}" IS NOT NULL) AS "{c}"' for c in columns)
    row = db.execute(text(f"SELECT {select_list} FROM {table} WHERE {where}"), params).mappings().one()  # noqa: S608
    return {c for c in columns if row[c]}


def test_generator_populates_every_column_the_api_create_path_populates(client, admin_token, org_id):
    headers = auth_headers(admin_token)
    project = create_project(client, admin_token, org_id, "API parity project")
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    base = f"/api/v1/projects/{project['id']}"
    first = client.post(
        f"{base}/requirements",
        headers=headers,
        json={"name": "First", "reasoning": "Because.", "component_id": component_id, "category_id": category_id, "keywords": ["alpha"]},
    ).json()
    second = client.post(
        f"{base}/requirements",
        headers=headers,
        json={"name": "Second", "reasoning": "Because.", "component_id": component_id, "category_id": category_id, "keywords": []},
    ).json()
    assert client.post(f"{base}/requirements/{first['id']}/comments", headers=headers, json={"body": "A comment."}).status_code == 201
    link_type = next(t for t in client.get(f"/api/v1/orgs/{org_id}/link-types", headers=headers).json() if not t.get("dedicated_endpoint"))
    assert (
        client.post(
            f"{base}/requirements/{first['id']}/links", headers=headers, json={"target_requirement_id": second["id"], "link_type_id": link_type["id"]}
        ).status_code
        == 201
    )
    action_type = client.get(f"{base}/action-types", headers=headers).json()[0]
    assert (
        client.post(
            f"{base}/requirements/{first['id']}/actions/create-and-link",
            headers=headers,
            json={"title": "Do it", "description": "Soon.", "action_type_id": action_type["id"]},
        ).status_code
        == 201
    )

    manifest = _generate(client, "single")
    generated = manifest["projects"][0]["id"]
    db = SessionLocal()
    try:
        checks = [
            ("requirements", "project_id = :p", {"p": uuid.UUID(project["id"])}, {"p": uuid.UUID(generated)}),
            (
                "requirement_versions",
                "requirement_id IN (SELECT id FROM requirements WHERE project_id = :p)",
                {"p": uuid.UUID(project["id"])},
                {"p": uuid.UUID(generated)},
            ),
            (
                "review_comments",
                "target_id IN (SELECT id FROM requirements WHERE project_id = :p)",
                {"p": uuid.UUID(project["id"])},
                {"p": uuid.UUID(generated)},
            ),
            ("requirement_actions", "project_id = :p", {"p": uuid.UUID(project["id"])}, {"p": uuid.UUID(generated)}),
            ("artefact_tags", "project_id = :p", {"p": uuid.UUID(project["id"])}, {"p": uuid.UUID(generated)}),
            (
                "audit_events",
                "project_id = :p AND entity_type = 'requirement' AND action = 'created'",
                {"p": uuid.UUID(project["id"])},
                {"p": uuid.UUID(generated)},
            ),
            ("audit_events", "project_id = :p AND entity_type = 'requirement_link'", {"p": uuid.UUID(project["id"])}, {"p": uuid.UUID(generated)}),
            ("audit_events", "project_id = :p AND entity_type = 'requirement_action'", {"p": uuid.UUID(project["id"])}, {"p": uuid.UUID(generated)}),
            ("audit_events", "project_id = :p AND action = 'tagged'", {"p": uuid.UUID(project["id"])}, {"p": uuid.UUID(generated)}),
            (
                "artefact_links",
                "source_type = 'requirement' AND source_id IN (SELECT id FROM requirements WHERE project_id = :p)",
                {"p": uuid.UUID(project["id"])},
                {"p": uuid.UUID(generated)},
            ),
            (
                "artefact_links",
                "source_type = 'requirement_action' AND target_id IN (SELECT id FROM requirements WHERE project_id = :p)",
                {"p": uuid.UUID(project["id"])},
                {"p": uuid.UUID(generated)},
            ),
        ]
        for table, where, api_params, generated_params in checks:
            from_api = _populated_columns(db, table, where, api_params)
            from_generator = _populated_columns(db, table, where, generated_params)
            assert from_api, f"the API wrote no {table} row for: {where}"
            assert from_api <= from_generator, f"{table} ({where}): the generator leaves {sorted(from_api - from_generator)} empty"
        tags = _populated_columns(db, "tags", "project_id = :p", {"p": uuid.UUID(project["id"])})
        assert tags <= _populated_columns(db, "tags", "project_id = :p", {"p": uuid.UUID(generated)})
        assert db.scalar(select(func.count()).select_from(Requirement).where(Requirement.project_id == uuid.UUID(generated))) == 30
    finally:
        db.close()


# --- registry: every type has a generator, a reason, or a tracked gap ------------------------------------


def test_every_registered_artefact_type_has_a_generator_a_reason_or_a_tracked_gap():
    generators = set(get_perf_generators())
    reasons = set(get_no_perf_generator_types())
    missing = get_all_registered_artefact_types() - generators - reasons - TRACKED_GAPS
    assert not missing, f"artefact types with no performance dataset generator and no stated reason: {sorted(missing)}"


def test_the_tracked_gap_list_only_names_types_still_without_a_generator():
    registered = get_all_registered_artefact_types()
    done = TRACKED_GAPS & (set(get_perf_generators()) | set(get_no_perf_generator_types()))
    assert not done, f"remove from TRACKED_GAPS, they now have a generator or reason: {sorted(done)}"
    assert not (TRACKED_GAPS - registered), f"TRACKED_GAPS names unregistered types: {sorted(TRACKED_GAPS - registered)}"


def test_core_generators_run_requirements_before_actions():
    generators = get_perf_generators()
    assert generators["requirement"].order < generators["requirement_action"].order
