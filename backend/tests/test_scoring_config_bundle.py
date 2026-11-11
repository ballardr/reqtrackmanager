"""Tests that a project's own scoring configuration (default model, offered models, bands, thresholds, cell ratings)
travels in the project bundle and into a project created from a template, matched by level name so it is never
re-rated against a different level."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.scoring import ScoringLevel, ScoringLevelThreshold
from tests.conftest import auth_headers
from tests.link_world import World

SCHEME = "pain_point"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Scoring Config Org", context_strategy=True)


def scheme_of(world: World, project_id: str) -> dict:
    resp = world.client.get(f"/api/v1/projects/{project_id}/scoring-schemes/{SCHEME}", headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def put(world: World, project_id: str, path: str, body: dict) -> None:
    resp = world.client.put(f"/api/v1/projects/{project_id}/scoring-schemes/{SCHEME}/{path}", json=body, headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text


def configure(world: World, project_id: str) -> None:
    """Gives the project a default model, an offered set, a band set and a cell-rating set of its own."""
    put(world, project_id, "default-model", {"model": "wsjf"})
    put(world, project_id, "enabled-models", {"models": ["sxf", "wsjf"]})
    put(world, project_id, "models/sxf/bands", {"bands": [
        {"label": "Tolerable", "min_score": 0, "tone": "muted"}, {"label": "Urgent", "min_score": 0.5, "tone": "danger"},
    ]})
    levels = {axis["key"]: axis["levels"] for axis in scheme_of(world, project_id)["axes"]}
    put(world, project_id, "models/sxf/cell-ratings", {"cells": [
        {"first_level_id": levels["severity"][-1]["id"], "second_level_id": levels["frequency"][0]["id"], "band_label": "Urgent"},
        {"first_level_id": levels["severity"][0]["id"], "second_level_id": levels["frequency"][-1]["id"], "band_label": "Tolerable"},
    ]})
    first_level = levels["severity"][1]["id"]
    db = SessionLocal()
    try:
        db.add(ScoringLevelThreshold(project_id=uuid.UUID(project_id), level_id=uuid.UUID(first_level), threshold=3))
        db.commit()
    finally:
        db.close()


def configuration(world: World, project_id: str) -> dict:
    """What a project's scoring reads as, in names a person sees (ids differ between projects but not levels)."""
    scheme = scheme_of(world, project_id)
    sxf = next(model for model in scheme["models"] if model["key"] == "sxf")
    db = SessionLocal()
    try:
        thresholds = sorted(
            (level.axis_key, level.name, float(row.threshold))
            for row, level in db.execute(
                select(ScoringLevelThreshold, ScoringLevel).join(ScoringLevel, ScoringLevel.id == ScoringLevelThreshold.level_id)
                .where(ScoringLevelThreshold.project_id == uuid.UUID(project_id))
            ).all()
        )
    finally:
        db.close()
    return {
        "default": (scheme["default_model_key"], scheme["default_model_source"]),
        "enabled": (sorted(scheme["enabled_model_keys"]), scheme["enabled_models_source"]),
        "bands": [(band["label"], band["min_score"], band["tone"]) for band in sxf["bands"]],
        "cells": sorted((cell["band_label"], cell["first_level_id"], cell["second_level_id"]) for cell in sxf["cell_ratings"]),
        "thresholds": thresholds,
    }


def test_a_project_bundle_carries_the_projects_scoring_configuration(world):
    project = world.project("Source")
    configure(world, project["id"])
    expected = configuration(world, project["id"])
    assert expected["default"] == ("wsjf", "project") and len(expected["cells"]) == 2 and expected["thresholds"]
    h = auth_headers(world.token)
    exported = world.client.get(f"/api/v1/projects/{project['id']}/export", headers=h)
    assert exported.status_code == 200, exported.text
    imported = world.client.post(
        "/api/v1/projects/import", data={"organization_id": world.org["id"], "name": "Imported"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=h,
    )
    assert imported.status_code == 201, imported.text
    assert configuration(world, imported.json()["project"]["id"]) == expected


def test_a_project_with_no_scoring_overrides_exports_and_imports_none(world):
    project = world.project("Plain")
    h = auth_headers(world.token)
    exported = world.client.get(f"/api/v1/projects/{project['id']}/export", headers=h)
    imported = world.client.post(
        "/api/v1/projects/import", data={"organization_id": world.org["id"], "name": "Imported plain"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=h,
    )
    assert imported.status_code == 201, imported.text
    config = configuration(world, imported.json()["project"]["id"])
    assert config["default"][1] != "project" and config["thresholds"] == []


def test_a_project_created_from_a_template_receives_the_templates_scoring_configuration(world):
    template = world.project("Template")
    configure(world, template["id"])
    h = auth_headers(world.token)
    assert world.client.patch(f"/api/v1/projects/{template['id']}", json={"is_template": True}, headers=h).status_code == 200
    created = world.client.post(
        "/api/v1/projects",
        json={"organization_id": world.org["id"], "name": "From template", "summary": "", "template_project_id": template["id"]},
        headers=h,
    )
    assert created.status_code == 201, created.text
    assert configuration(world, created.json()["id"]) == configuration(world, template["id"])


def test_a_level_the_target_organisation_lacks_is_skipped_with_a_warning(world):
    from app.services.bundle_common import BundleImportWarnings
    from app.services.scoring_config import import_project_scoring

    project = world.project("Target")
    data = {"scoring_configuration": {
        "default_models": [{"scheme": SCHEME, "model": "nonexistent"}],
        "level_thresholds": [{"scheme": SCHEME, "axis": "severity", "level": "No such level", "threshold": "2"}],
    }}
    warnings = BundleImportWarnings()
    db = SessionLocal()
    try:
        from app.models.project import Project

        import_project_scoring(db, db.get(Project, uuid.UUID(project["id"])), data, warnings)
        db.rollback()
    finally:
        db.close()
    assert len(warnings.messages) == 2 and all("not imported" in m for m in warnings.messages)


def test_a_default_that_names_a_projects_own_model_follows_the_model_to_a_project_made_from_the_template(world):
    template = world.project("Own model template")
    h = auth_headers(world.token)
    made = world.client.post(
        f"/api/v1/projects/{template['id']}/scoring-schemes/{SCHEME}/models",
        json={"label": "Value over size", "combination": "product", "axes": [{"axis_key": "severity", "role": "multiply"}]}, headers=h,
    )
    assert made.status_code == 201, made.text
    own = next(model for model in made.json()["models"] if model["label"] == "Value over size")
    put(world, template["id"], "default-model", {"model": own["key"]})
    assert world.client.patch(f"/api/v1/projects/{template['id']}", json={"is_template": True}, headers=h).status_code == 200
    created = world.client.post(
        "/api/v1/projects",
        json={"organization_id": world.org["id"], "name": "Own model child", "summary": "", "template_project_id": template["id"]},
        headers=h,
    )
    assert created.status_code == 201, created.text
    scheme = scheme_of(world, created.json()["id"])
    chosen = next(model for model in scheme["models"] if model["key"] == scheme["default_model_key"])
    assert (chosen["label"], scheme["default_model_source"]) == ("Value over size", "project")
