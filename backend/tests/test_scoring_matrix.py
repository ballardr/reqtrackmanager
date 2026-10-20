"""Tests for the generic scoring-matrix core (Context & Strategy
): `ScoringSchemeDefinition` validation, score maths, level
seeding (org creation and startup sync), level CRUD rules, the
project → ancestor → org → system resolution of default model and bands,
permission/enablement gating and cross-org isolation.

Uses a fake module registering its own scheme (with level-usage hooks), so
the core is tested independently of any real module — Context & Strategy's
own registration is covered by `test_context_strategy_scoring.py`.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.scoring import ScoringLevel
from app.modules import registry as module_registry
from app.modules.registry import (
    ModuleDefinition,
    ScoringAxisDefinition,
    ScoringBandDefault,
    ScoringLevelDefault,
    ScoringModelDefinition,
    ScoringSchemeDefinition,
    build_registry,
    validate_scoring_bands,
)
from app.services.scoring import BandValue, CellRatings, band_for, compute_score, sync_scoring_levels
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login

FAKE_MODULE_KEY = "fake_scoring_module"
SCHEME = "fake_scheme"

# Simulated module rows referencing levels: level_id -> reference count.
_USAGE: dict[uuid.UUID, int] = {}


def _count_usage(_db, level_id: uuid.UUID) -> int:
    return _USAGE.get(level_id, 0)


def _reassign_usage(_db, from_id: uuid.UUID, to_id: uuid.UUID) -> None:
    _USAGE[to_id] = _USAGE.get(to_id, 0) + _USAGE.pop(from_id, 0)


def _scheme(**overrides) -> ScoringSchemeDefinition:
    defaults = dict(
        key=SCHEME, label="Fake scoring",
        axes=(
            ScoringAxisDefinition("impact", "Impact", (
                ScoringLevelDefault("Low", 1), ScoringLevelDefault("Mid", 2), ScoringLevelDefault("Top", 4),
            )),
            ScoringAxisDefinition("likelihood", "Likelihood", (
                ScoringLevelDefault("Unlikely", 1), ScoringLevelDefault("Likely", 2),
            )),
        ),
        models=(
            ScoringModelDefinition("ixl", "Impact × Likelihood", ("impact", "likelihood"), (
                ScoringBandDefault("Low", 0, "muted"), ScoringBandDefault("High", 0.5, "danger"),
            )),
            ScoringModelDefinition("i", "Impact only", ("impact",)),
        ),
        default_model_key="ixl",
        count_level_usage=_count_usage, reassign_level_usage=_reassign_usage,
    )
    defaults.update(overrides)
    return ScoringSchemeDefinition(**defaults)


@pytest.fixture
def fake_scoring_module():
    """Registers a fake module with one scoring scheme for one test."""
    _USAGE.clear()
    module_registry.INSTALLED_MODULES.append(ModuleDefinition(
        key=FAKE_MODULE_KEY, name="Fake Scoring Module", description="Test-only scoring scheme.",
        version="0.0.1", default_enabled=True, implemented=False, get_router=lambda: None,
        scoring_schemes=(_scheme(),),
    ))
    build_registry(force=True)
    yield
    module_registry.INSTALLED_MODULES[:] = [m for m in module_registry.INSTALLED_MODULES if m.key != FAKE_MODULE_KEY]
    build_registry(force=True)
    _USAGE.clear()


def _org_base(org_id: str) -> str:
    return f"/api/v1/orgs/{org_id}/scoring-schemes/{SCHEME}"


def _project_base(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/scoring-schemes/{SCHEME}"


def _get(client, url, token):
    resp = client.get(url, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _axis(config: dict, key: str) -> dict:
    return next(a for a in config["axes"] if a["key"] == key)


def _model(config: dict, key: str) -> dict:
    return next(m for m in config["models"] if m["key"] == key)


# --- Pure: definition validation and maths ----------------------------------


@pytest.mark.parametrize("overrides, message", [
    ({"key": "Bad Key"}, "Invalid scoring scheme key"),
    ({"default_model_key": "nope"}, "Default model"),
    ({"models": (ScoringModelDefinition("x", "X", ("missing",)),)}, "must combine distinct axes"),
    ({"axes": (ScoringAxisDefinition("a", "A", (ScoringLevelDefault("Only", 1),)),),
      "models": (ScoringModelDefinition("m", "M", ("a",)),), "default_model_key": "m"}, "≥2 levels"),
    ({"axes": (ScoringAxisDefinition("a", "A", (ScoringLevelDefault("X", 1), ScoringLevelDefault("Y", 1))),),
      "models": (ScoringModelDefinition("m", "M", ("a",)),), "default_model_key": "m"}, "unique positive weights"),
    ({"reassign_level_usage": None}, "supplied together"),
])
def test_scheme_definition_rejects_inconsistent_config(overrides, message):
    with pytest.raises(ValueError, match=message):
        _scheme(**overrides)


@pytest.mark.parametrize("bands, message", [
    ([], "between 1 and"),
    ([("Low", 0.1, "muted")], "start at 0"),
    ([("Low", 0, "muted"), ("High", 0, "danger")], "strictly increasing"),
    ([("Low", 0, "muted"), ("low", 0.5, "danger")], "Duplicate"),
    ([("Low", 0, "purple")], "Unknown band tone"),
])
def test_band_validation(bands, message):
    with pytest.raises(ValueError, match=message):
        validate_scoring_bands(bands)


def test_compute_score_is_product_normalised_and_banded():
    model = ScoringModelDefinition("ixl", "IxL", ("impact", "likelihood"))
    bands = [BandValue("Low", 0, "muted"), BandValue("High", 0.5, "danger")]
    maxima = {"impact": Decimal(4), "likelihood": Decimal(2)}
    result = compute_score(model, {"impact": Decimal(2), "likelihood": Decimal(2)}, maxima, bands)
    assert result is not None
    assert result.raw == Decimal(4) and result.normalised == 0.5 and result.band.label == "High"
    low = compute_score(model, {"impact": Decimal(1), "likelihood": Decimal(1)}, maxima, bands)
    assert low.normalised == 0.125 and low.band.label == "Low"
    # A missing input means "not scored under this model", not zero.
    assert compute_score(model, {"impact": Decimal(4), "likelihood": None}, maxima, bands) is None
    assert compute_score(model, {"impact": Decimal(4)}, maxima, bands) is None
    assert band_for(0.9, []) is None


def test_compute_score_cell_rating_overrides_only_its_cell_and_ignores_stale_labels():
    model = ScoringModelDefinition("ixl", "IxL", ("impact", "likelihood"))
    bands = [BandValue("Low", 0, "muted"), BandValue("High", 0.5, "danger")]
    maxima = {"impact": Decimal(4), "likelihood": Decimal(2)}
    weights = {"impact": Decimal(4), "likelihood": Decimal(1)}  # normalised 0.5 -> thresholds say High
    top, unlikely = uuid.uuid4(), uuid.uuid4()
    levels = {"impact": top, "likelihood": unlikely}

    # Non-monotonic on purpose: the 4 x 1 cell is rated Low although its product reaches the High threshold.
    cells = CellRatings({(top, unlikely): "Low"})
    assert compute_score(model, weights, maxima, bands, level_ids=levels, cell_ratings=cells).band.label == "Low"
    # Other cells, a missing level id, and no override at all keep the thresholds.
    other = {"impact": top, "likelihood": uuid.uuid4()}
    assert compute_score(model, weights, maxima, bands, level_ids=other, cell_ratings=cells).band.label == "High"
    assert compute_score(model, weights, maxima, bands, cell_ratings=cells).band.label == "High"
    assert compute_score(model, weights, maxima, bands, level_ids=levels).band.label == "High"
    # A label that is no longer in the band set is ignored.
    stale = CellRatings({(top, unlikely): "Gone"})
    assert compute_score(model, weights, maxima, bands, level_ids=levels, cell_ratings=stale).band.label == "High"
    # Only two-axis models take cell ratings.
    single = ScoringModelDefinition("i", "I", ("impact",))
    assert compute_score(single, {"impact": Decimal(4)}, maxima, bands, level_ids={"impact": top},
                         cell_ratings=cells).band.label == "High"


# --- Seeding ----------------------------------------------------------------


def test_new_org_is_seeded_with_default_levels_ordered_by_weight(client, admin_token, fake_scoring_module):
    org, token = create_org_admin_in(client, admin_token, "Scoring Seed Co")
    config = _get(client, _org_base(org["id"]), token)
    assert [lvl["name"] for lvl in _axis(config, "impact")["levels"]] == ["Low", "Mid", "Top"]
    assert [lvl["weight"] for lvl in _axis(config, "likelihood")["levels"]] == [1, 2]


def test_startup_sync_seeds_orgs_created_before_the_module_was_installed(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Scoring Late Module Co")
    _USAGE.clear()
    module_registry.INSTALLED_MODULES.append(ModuleDefinition(
        key=FAKE_MODULE_KEY, name="Fake", description="", version="0.0.1", default_enabled=True,
        implemented=False, get_router=lambda: None, scoring_schemes=(_scheme(),),
    ))
    build_registry(force=True)
    try:
        db = SessionLocal()
        try:
            assert not db.scalars(select(ScoringLevel).where(ScoringLevel.scheme_key == SCHEME)).all()
            sync_scoring_levels(db)
            sync_scoring_levels(db)  # idempotent
            rows = db.scalars(select(ScoringLevel).where(
                ScoringLevel.scheme_key == SCHEME, ScoringLevel.organization_id == uuid.UUID(org["id"]),
            )).all()
            assert len(rows) == 5
        finally:
            db.close()
        assert len(_axis(_get(client, _org_base(org["id"]), token), "impact")["levels"]) == 3
    finally:
        module_registry.INSTALLED_MODULES[:] = [
            m for m in module_registry.INSTALLED_MODULES if m.key != FAKE_MODULE_KEY
        ]
        build_registry(force=True)


# --- Level CRUD ---------------------------------------------------------------


def test_level_create_update_rules_and_audit(client, admin_token, fake_scoring_module):
    org, token = create_org_admin_in(client, admin_token, "Scoring Levels Co")
    base = _org_base(org["id"])
    resp = client.post(f"{base}/axes/impact/levels", json={"name": "Severe", "weight": 3, "description": "Bad"},
                       headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    level_id = resp.json()["id"]
    names = [lvl["name"] for lvl in _axis(_get(client, base, token), "impact")["levels"]]
    assert names == ["Low", "Mid", "Severe", "Top"]  # ordered by weight

    dup_name = client.post(f"{base}/axes/impact/levels", json={"name": "severe", "weight": 9}, headers=auth_headers(token))
    dup_weight = client.post(f"{base}/axes/impact/levels", json={"name": "Other", "weight": 2}, headers=auth_headers(token))
    unknown_axis = client.post(f"{base}/axes/nope/levels", json={"name": "X", "weight": 9}, headers=auth_headers(token))
    assert (dup_name.status_code, dup_weight.status_code, unknown_axis.status_code) == (400, 400, 404)

    resp = client.patch(f"{base}/levels/{level_id}", json={"name": "Critical", "weight": 5, "description": None},
                        headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"id": level_id, "name": "Critical", "description": None, "weight": 5}
    names = [lvl["name"] for lvl in _axis(_get(client, base, token), "impact")["levels"]]
    assert names[-1] == "Critical"  # re-weighting reorders, and it is now the top level

    db = SessionLocal()
    try:
        actions = db.scalars(select(AuditEvent.action).where(
            AuditEvent.entity_type == "scoring_level", AuditEvent.entity_id == level_id,
        )).all()
    finally:
        db.close()
    assert sorted(actions) == ["created", "updated"]


def test_weights_are_validated_at_stored_precision(client, admin_token, fake_scoring_module):
    """Weights are quantised to the column's 4 decimals before validation, so
    a value that would round to 0 or onto an existing weight is a clean 400,
    never a silent zero or a 500 from the unique constraint."""
    org, token = create_org_admin_in(client, admin_token, "Scoring Precision Co")
    base = _org_base(org["id"])
    too_small = client.post(f"{base}/axes/impact/levels", json={"name": "Tiny", "weight": 0.00001}, headers=auth_headers(token))
    rounds_onto_low = client.post(f"{base}/axes/impact/levels", json={"name": "Lowish", "weight": 1.00001},
                                  headers=auth_headers(token))
    assert (too_small.status_code, rounds_onto_low.status_code) == (400, 400)


def test_level_delete_floor_and_reassignment(client, admin_token, fake_scoring_module):
    org, token = create_org_admin_in(client, admin_token, "Scoring Delete Co")
    base = _org_base(org["id"])
    config = _get(client, base, token)
    likelihood = _axis(config, "likelihood")["levels"]
    impact = _axis(config, "impact")["levels"]

    # An axis can't drop below two levels.
    resp = client.delete(f"{base}/levels/{likelihood[0]['id']}", headers=auth_headers(token))
    assert resp.status_code == 409

    low, mid = uuid.UUID(impact[0]["id"]), uuid.UUID(impact[1]["id"])
    _USAGE[low] = 3
    resp = client.delete(f"{base}/levels/{low}", headers=auth_headers(token))
    assert resp.status_code == 409 and "3 score" in resp.json()["detail"]
    # Reassigning to a level on another axis, or to itself, is rejected.
    for target in (likelihood[1]["id"], str(low)):
        resp = client.delete(f"{base}/levels/{low}?reassign_to_id={target}", headers=auth_headers(token))
        assert resp.status_code == 400
    resp = client.delete(f"{base}/levels/{low}?reassign_to_id={mid}", headers=auth_headers(token))
    assert resp.status_code == 204, resp.text
    assert _USAGE == {mid: 3}
    assert [lvl["name"] for lvl in _axis(_get(client, base, token), "impact")["levels"]] == ["Mid", "Top"]


# --- Default model and band resolution --------------------------------------


def test_default_model_resolves_project_ancestor_org_system(client, admin_token, fake_scoring_module):
    org, token = create_org_admin_in(client, admin_token, "Scoring Model Co")
    parent = create_project(client, token, org["id"], "Parent", can_be_parent=True)
    child = create_project(client, token, org["id"], "Child", parent_project_id=parent["id"])

    def model_of(project):
        config = _get(client, _project_base(project["id"]), token)
        return config["default_model_key"], config["default_model_source"]

    assert model_of(child) == ("ixl", "system")
    resp = client.put(f"{_org_base(org['id'])}/default-model", json={"model": "i"}, headers=auth_headers(token))
    assert resp.status_code == 200 and resp.json()["default_model_source"] == "org"
    assert model_of(child) == ("i", "org")

    resp = client.put(f"{_project_base(parent['id'])}/default-model", json={"model": "ixl"}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert model_of(parent) == ("ixl", "project")
    assert model_of(child) == ("ixl", "ancestor")

    client.put(f"{_project_base(child['id'])}/default-model", json={"model": "i"}, headers=auth_headers(token))
    assert model_of(child) == ("i", "project")
    client.put(f"{_project_base(child['id'])}/default-model", json={"model": None}, headers=auth_headers(token))
    assert model_of(child) == ("ixl", "ancestor")

    resp = client.put(f"{_project_base(child['id'])}/default-model", json={"model": "nope"}, headers=auth_headers(token))
    assert resp.status_code == 400


def test_bands_resolve_and_validate(client, admin_token, fake_scoring_module):
    org, token = create_org_admin_in(client, admin_token, "Scoring Bands Co")
    parent = create_project(client, token, org["id"], "Parent", can_be_parent=True)
    child = create_project(client, token, org["id"], "Child", parent_project_id=parent["id"])

    def bands_of(project, model="ixl"):
        m = _model(_get(client, _project_base(project["id"]), token), model)
        return [b["label"] for b in m["bands"]], m["bands_source"]

    assert bands_of(child) == (["Low", "High"], "system")
    assert bands_of(child, "i") == ([], "none")

    org_bands = [{"label": "Ok", "min_score": 0, "tone": "accent"}, {"label": "Bad", "min_score": 0.6, "tone": "danger"}]
    resp = client.put(f"{_org_base(org['id'])}/models/ixl/bands", json={"bands": org_bands}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert bands_of(child) == (["Ok", "Bad"], "org")

    parent_bands = [{"label": "P", "min_score": 0, "tone": "muted"}]
    client.put(f"{_project_base(parent['id'])}/models/ixl/bands", json={"bands": parent_bands}, headers=auth_headers(token))
    assert bands_of(child) == (["P"], "ancestor")
    assert bands_of(parent) == (["P"], "project")

    bad = [{"label": "A", "min_score": 0.2, "tone": "muted"}]
    resp = client.put(f"{_project_base(child['id'])}/models/ixl/bands", json={"bands": bad}, headers=auth_headers(token))
    assert resp.status_code == 400
    resp = client.put(f"{_project_base(child['id'])}/models/nope/bands", json={"bands": parent_bands},
                      headers=auth_headers(token))
    assert resp.status_code == 400

    client.put(f"{_project_base(parent['id'])}/models/ixl/bands", json={"bands": None}, headers=auth_headers(token))
    client.put(f"{_org_base(org['id'])}/models/ixl/bands", json={"bands": None}, headers=auth_headers(token))
    assert bands_of(child) == (["Low", "High"], "system")


# --- Gating and isolation ---------------------------------------------------------


def test_member_can_read_but_not_write(client, admin_token, fake_scoring_module):
    org, token = create_org_admin_in(client, admin_token, "Scoring Gate Co")
    project = create_project(client, token, org["id"], "Gate Project")
    member_id = create_org_user(client, token, org["id"], "scoring_member@example.com")
    client.post(f"/api/v1/projects/{project['id']}/roles", json={"user_id": member_id, "role": "member"},
                headers=auth_headers(token))
    member = login(client, "scoring_member@example.com", "Password123!")

    config = _get(client, _org_base(org["id"]), member)
    level_id = _axis(config, "impact")["levels"][0]["id"]
    _get(client, _project_base(project["id"]), member)
    for method, url, body in [
        ("post", f"{_org_base(org['id'])}/axes/impact/levels", {"name": "X", "weight": 9}),
        ("patch", f"{_org_base(org['id'])}/levels/{level_id}", {"name": "X"}),
        ("put", f"{_org_base(org['id'])}/default-model", {"model": "i"}),
        ("put", f"{_org_base(org['id'])}/models/ixl/bands", {"bands": None}),
        ("put", f"{_project_base(project['id'])}/default-model", {"model": "i"}),
        ("put", f"{_project_base(project['id'])}/models/ixl/bands", {"bands": None}),
        ("put", f"{_org_base(org['id'])}/models/ixl/cell-ratings", {"cells": None}),
        ("put", f"{_project_base(project['id'])}/models/ixl/cell-ratings", {"cells": None}),
    ]:
        resp = getattr(client, method)(url, json=body, headers=auth_headers(member))
        assert resp.status_code == 403, (url, resp.text)
    resp = client.delete(f"{_org_base(org['id'])}/levels/{level_id}", headers=auth_headers(member))
    assert resp.status_code == 403


def test_disabled_module_unknown_scheme_and_cross_org_isolation(client, admin_token, fake_scoring_module):
    org_a, token_a = create_org_admin_in(client, admin_token, "Scoring Iso A")
    org_b, token_b = create_org_admin_in(client, admin_token, "Scoring Iso B")
    project_a = create_project(client, token_a, org_a["id"], "Iso Project")
    level_a = _axis(_get(client, _org_base(org_a["id"]), token_a), "impact")["levels"][0]["id"]

    # Org B's admin can't see org A, nor reach org A's level through org B's path.
    assert client.get(_org_base(org_a["id"]), headers=auth_headers(token_b)).status_code == 404
    assert client.get(_project_base(project_a["id"]), headers=auth_headers(token_b)).status_code == 403
    resp = client.patch(f"{_org_base(org_b['id'])}/levels/{level_a}", json={"name": "Hijack"}, headers=auth_headers(token_b))
    assert resp.status_code == 404

    unknown = client.get(f"/api/v1/orgs/{org_a['id']}/scoring-schemes/nope", headers=auth_headers(token_a))
    assert unknown.status_code == 404

    resp = client.put(f"/api/v1/orgs/{org_a['id']}/modules/{FAKE_MODULE_KEY}", json={"enabled": False},
                      headers=auth_headers(token_a))
    assert resp.status_code == 200, resp.text
    assert client.get(_org_base(org_a["id"]), headers=auth_headers(token_a)).status_code == 404
    assert client.get(_project_base(project_a["id"]), headers=auth_headers(token_a)).status_code == 404
    listed = _get(client, f"/api/v1/orgs/{org_a['id']}/scoring-schemes", token_a)
    assert SCHEME not in {s["key"] for s in listed}


# --- Per-cell rating overrides ---------------------------


def _cell(first: dict, second: dict, label: str) -> dict:
    return {"first_level_id": first["id"], "second_level_id": second["id"], "band_label": label}


def _cells_of(client, url, token, model="ixl"):
    m = _model(_get(client, url, token), model)
    return {(c["first_level_id"], c["second_level_id"]): c["band_label"] for c in m["cell_ratings"]}, m["cell_ratings_source"]


def test_cell_ratings_resolve_validate_and_clear(client, admin_token, fake_scoring_module):
    org, token = create_org_admin_in(client, admin_token, "Scoring Cells Co")
    parent = create_project(client, token, org["id"], "Parent", can_be_parent=True)
    child = create_project(client, token, org["id"], "Child", parent_project_id=parent["id"])
    config = _get(client, _org_base(org["id"]), token)
    impact, likelihood = _axis(config, "impact")["levels"], _axis(config, "likelihood")["levels"]
    org_cells = f"{_org_base(org['id'])}/models/ixl/cell-ratings"
    parent_cells = f"{_project_base(parent['id'])}/models/ixl/cell-ratings"
    child_cells = f"{_project_base(child['id'])}/models/ixl/cell-ratings"
    put = lambda url, cells: client.put(url, json={"cells": cells}, headers=auth_headers(token))  # noqa: E731

    assert _cells_of(client, _project_base(child["id"]), token) == ({}, "none")

    # Org set, inherited down the chain. The registry's default bands (Low/High) are valid labels.
    org_set = [_cell(impact[2], likelihood[0], "Low"), _cell(impact[0], likelihood[1], "High")]
    resp = put(org_cells, org_set)
    assert resp.status_code == 200, resp.text
    expected_org = {(impact[2]["id"], likelihood[0]["id"]): "Low", (impact[0]["id"], likelihood[1]["id"]): "High"}
    assert _cells_of(client, _project_base(child["id"]), token) == (expected_org, "org")

    # A project set replaces the inherited one wholesale, and its own descendants inherit it.
    assert put(parent_cells, [_cell(impact[1], likelihood[1], "Low")]).status_code == 200
    assert _cells_of(client, _project_base(child["id"]), token) == (
        {(impact[1]["id"], likelihood[1]["id"]): "Low"}, "ancestor")
    assert _cells_of(client, _project_base(parent["id"]), token)[1] == "project"
    assert _cells_of(client, _org_base(org["id"]), token) == (expected_org, "org")

    # Rejected: unknown band, a level on the wrong axis (swapped), duplicates, a single-axis model.
    assert put(child_cells, [_cell(impact[0], likelihood[0], "Nope")]).status_code == 400
    assert put(child_cells, [_cell(likelihood[0], impact[0], "Low")]).status_code == 400
    assert put(child_cells, [_cell(impact[0], likelihood[0], "Low")] * 2).status_code == 400
    assert put(f"{_project_base(child['id'])}/models/i/cell-ratings", [_cell(impact[0], impact[1], "Low")]).status_code == 400
    assert put(f"{_project_base(child['id'])}/models/nope/cell-ratings", [_cell(impact[0], likelihood[0], "Low")]).status_code == 400
    assert _cells_of(client, _project_base(child["id"]), token)[1] == "ancestor"

    # Clearing (null or empty) inherits again.
    assert put(parent_cells, None).status_code == 200
    assert _cells_of(client, _project_base(child["id"]), token) == (expected_org, "org")
    assert put(org_cells, []).status_code == 200
    assert _cells_of(client, _project_base(child["id"]), token) == ({}, "none")

    with SessionLocal() as db:
        actions = [e.action for e in db.scalars(select(AuditEvent).where(
            AuditEvent.entity_type == "scoring_cell_rating_set", AuditEvent.organization_id == uuid.UUID(org["id"])
        ).order_by(AuditEvent.created_at)).all()]
    assert actions == ["set", "set", "reset", "reset"]


def test_cell_ratings_and_bands_stay_consistent(client, admin_token, fake_scoring_module):
    org, token = create_org_admin_in(client, admin_token, "Scoring Cells Bands Co")
    project = create_project(client, token, org["id"], "Cells Project")
    config = _get(client, _org_base(org["id"]), token)
    impact, likelihood = _axis(config, "impact")["levels"], _axis(config, "likelihood")["levels"]
    bands_url = f"{_project_base(project['id'])}/models/ixl/bands"
    cells_url = f"{_project_base(project['id'])}/models/ixl/cell-ratings"
    own_bands = [{"label": "Fine", "min_score": 0, "tone": "accent"}, {"label": "Awful", "min_score": 0.5, "tone": "danger"}]

    # A cell can only use a label from the scope's *effective* bands.
    assert client.put(bands_url, json={"bands": own_bands}, headers=auth_headers(token)).status_code == 200
    assert client.put(cells_url, json={"cells": [_cell(impact[0], likelihood[0], "Low")]},
                      headers=auth_headers(token)).status_code == 400
    assert client.put(cells_url, json={"cells": [_cell(impact[0], likelihood[0], "Awful")]},
                      headers=auth_headers(token)).status_code == 200

    # Bands the scope's own cells still use can't be removed or renamed away...
    renamed = [{"label": "Fine", "min_score": 0, "tone": "accent"}, {"label": "Bad", "min_score": 0.5, "tone": "danger"}]
    resp = client.put(bands_url, json={"bands": renamed}, headers=auth_headers(token))
    assert resp.status_code == 400 and "Awful" in resp.json()["detail"]
    # ...nor can clearing them (the inherited defaults have no "Awful"), until the cells change.
    assert client.put(bands_url, json={"bands": None}, headers=auth_headers(token)).status_code == 400
    assert client.put(cells_url, json={"cells": None}, headers=auth_headers(token)).status_code == 200
    assert client.put(bands_url, json={"bands": renamed}, headers=auth_headers(token)).status_code == 200


def test_deleting_a_level_removes_its_cell_ratings(client, admin_token, fake_scoring_module):
    org, token = create_org_admin_in(client, admin_token, "Scoring Cells Delete Co")
    config = _get(client, _org_base(org["id"]), token)
    impact, likelihood = _axis(config, "impact")["levels"], _axis(config, "likelihood")["levels"]
    url = f"{_org_base(org['id'])}/models/ixl/cell-ratings"
    cells = [_cell(impact[0], likelihood[0], "High"), _cell(impact[1], likelihood[0], "Low")]
    assert client.put(url, json={"cells": cells}, headers=auth_headers(token)).status_code == 200
    resp = client.delete(f"{_org_base(org['id'])}/levels/{impact[0]['id']}", headers=auth_headers(token))
    assert resp.status_code == 204, resp.text
    assert _cells_of(client, _org_base(org["id"]), token) == ({(impact[1]["id"], likelihood[0]["id"]): "Low"}, "org")


def test_cell_ratings_are_scoped_to_their_org_and_project_managers(client, admin_token, fake_scoring_module):
    org_a, token_a = create_org_admin_in(client, admin_token, "Scoring Cells Iso A")
    org_b, token_b = create_org_admin_in(client, admin_token, "Scoring Cells Iso B")
    project_a = create_project(client, token_a, org_a["id"], "Iso Project")
    config_a = _get(client, _org_base(org_a["id"]), token_a)
    cell = _cell(_axis(config_a, "impact")["levels"][0], _axis(config_a, "likelihood")["levels"][0], "Low")
    # Another org's levels can't be used, and org B can't write to org A's endpoints.
    config_b = _get(client, _org_base(org_b["id"]), token_b)
    foreign = _cell(_axis(config_b, "impact")["levels"][0], _axis(config_b, "likelihood")["levels"][0], "Low")
    resp = client.put(f"{_org_base(org_a['id'])}/models/ixl/cell-ratings", json={"cells": [foreign]},
                      headers=auth_headers(token_a))
    assert resp.status_code == 400
    assert client.put(f"{_org_base(org_a['id'])}/models/ixl/cell-ratings", json={"cells": [cell]},
                      headers=auth_headers(token_b)).status_code == 404
    assert client.put(f"{_project_base(project_a['id'])}/models/ixl/cell-ratings", json={"cells": [cell]},
                      headers=auth_headers(token_b)).status_code == 403
