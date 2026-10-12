"""Tests for Risk bundle export/import (`export.py`): a project's Risks (current
content, status, original codes, evidence, reviews and requirement treatment
links with their verdicts) and type rows survive `GET /projects/{id}/export` +
`POST /projects/import`, and an organisation's Risk types survive
`GET /orgs/{id}/export` + `POST /orgs/import`. Version history and comments
deliberately do not travel (see `export.py`). Every test builds its own
organisation.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import date, timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.modules.risk_management.models import RiskTypeDefinition
from app.modules.risk_management.tests._helpers import (
    add_effective_treatment,
    assess,
    create_requirement,
    create_risk,
    levels,
    mitigate_with_requirement,
    project_base,
    setup,
)
from tests.conftest import auth_headers


def _days(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def _export(client, token, project_id) -> bytes:
    resp = client.get(f"/api/v1/projects/{project_id}/export", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.content


def _import(client, token, org_id, bundle: bytes, name: str) -> dict:
    resp = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": name},
        files={"file": ("bundle.zip", bundle, "application/zip")}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _risks(client, token, project_id, **params) -> dict[str, dict]:
    resp = client.get(project_base(project_id) + "/risks", params=params, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return {r["unique_code"]: r for r in resp.json()}


def _edit_bundle(bundle: bytes, edit) -> bytes:
    """Returns `bundle` with `project.json` passed through `edit(dict)`."""
    source = zipfile.ZipFile(io.BytesIO(bundle))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "project.json":
                doc = json.loads(data)
                edit(doc)
                data = json.dumps(doc).encode()
            target.writestr(item, data)
    return out.getvalue()


def _build_rich_project(client, token, org, project) -> dict[str, dict]:
    """A project with a local type, a treated and reviewed risk with evidence, a stale-verdict risk and an archived one."""
    h = auth_headers(token)
    base = project_base(project["id"])
    lv = levels(client, token, project["id"])
    me = client.get("/api/v1/auth/me", headers=h).json()["id"]
    local = client.post(base + "/risk-types", json={"name": "Project-only"}, headers=h)
    assert local.status_code == 201, local.text
    org_types = {t["name"]: t["id"] for t in client.get(base + "/risk-types", headers=h).json()}

    main = create_risk(
        client, token, project["id"], title="Flight controller fails", risk_type_id=local.json()["id"], owner_id=me,
        treatment_strategy="mitigate", acceptance_criteria="Redundant architecture certified.", review_date=_days(40),
        inherent_likelihood_level_id=lv["likelihood"]["Possible"], inherent_consequence_level_id=lv["consequence"]["Catastrophic"],
        residual_likelihood_level_id=lv["likelihood"]["Unlikely"], residual_consequence_level_id=lv["consequence"]["Major"],
    )
    add_effective_treatment(client, token, org, project, main["id"])
    for status in ("assessed", "treatment_planned", "treatment_in_progress"):
        assert client.post(f"{base}/risks/{main['id']}/transition", json={"status": status, "comment": ""}, headers=h).status_code == 200
    assert client.post(
        f"{base}/risks/{main['id']}/files", files={"file": ("evidence.txt", b"test report", "text/plain")}, headers=h,
    ).status_code == 201
    assert client.post(
        f"{base}/risks/{main['id']}/reviews",
        json={"outcome": "confirmed", "notes": "Still holds.", "next_review_date": _days(45)}, headers=h,
    ).status_code == 201

    stale = create_risk(
        client, token, project["id"], title="Stale verdict", risk_type_id=org_types["Cost"],
        inherent_likelihood_level_id=lv["likelihood"]["Likely"], inherent_consequence_level_id=lv["consequence"]["Major"],
    )
    link_id, _ = mitigate_with_requirement(client, token, org, project, stale["id"])
    assert assess(client, token, project["id"], stale["id"], link_id, status="needs_reassessment", rationale="").status_code == 200

    archived = create_risk(client, token, project["id"], title="Dropped idea")
    assert client.post(f"{base}/risks/{archived['id']}/archive", headers=h).status_code == 200
    return {"main": main, "stale": stale, "archived": archived}


def test_project_export_import_round_trips_risks(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Bundle Co")
    h = auth_headers(token)
    built = _build_rich_project(client, token, org, project)
    before = _risks(client, token, project["id"], include_archived=True)

    bundle = _export(client, token, project["id"])
    exported = json.loads(zipfile.ZipFile(io.BytesIO(bundle)).read("project.json"))
    assert {r["unique_code"] for r in exported["risks"]} == set(before)
    assert not any("rating" in r for r in exported["risks"])  # ratings are derived, never exported

    imported = _import(client, token, org["id"], bundle, "Risk Bundle Reimported")
    assert imported["warnings"] == []
    new_id = imported["project"]["id"]
    after = _risks(client, token, new_id, include_archived=True)

    assert set(after) == set(before)  # original codes are kept
    old, new = before[built["main"]["unique_code"]], after[built["main"]["unique_code"]]
    for field in ("title", "statement", "cause", "risk_event", "consequence", "acceptance_criteria", "treatment_strategy", "status",
                  "review_date", "owner_id", "risk_type_name"):
        assert new[field] == old[field], field
    assert new["status"] == "treatment_in_progress" and new["risk_type_name"] == "Project-only"
    assert new["inherent_rating"]["label"] == old["inherent_rating"]["label"] == "High"
    assert new["residual_rating"]["label"] == old["residual_rating"]["label"]
    assert new["effective_treatment_count"] == 1 and new["is_effectively_treated"]
    assert after[built["archived"]["unique_code"]]["is_archived"] is True
    assert after[built["stale"]["unique_code"]]["risk_type_name"] == "Cost"

    new_base = project_base(new_id)
    treatments = client.get(f"{new_base}/risks/{new['id']}/treatments", headers=h).json()
    assert [t["status"] for t in treatments["items"]] == ["effective"]
    stale_treatments = client.get(f"{new_base}/risks/{after[built['stale']['unique_code']]['id']}/treatments", headers=h).json()
    assert [t["status"] for t in stale_treatments["items"]] == ["needs_reassessment"]  # doubt is not turned into trust

    reviews = client.get(f"{new_base}/risks/{new['id']}/reviews", headers=h).json()
    assert [(r["outcome"], r["notes"], r["inherent_rating_label"]) for r in reviews] == [("confirmed", "Still holds.", "High")]
    files = client.get(f"{new_base}/risks/{new['id']}/files", headers=h).json()
    assert [f["filename"] for f in files] == ["evidence.txt"]

    # A risk created after the import continues the sequence instead of reusing a code.
    fresh = create_risk(client, token, new_id, title="Created after import")
    assert fresh["unique_code"] not in after
    assert int(fresh["unique_code"].rsplit("-", 1)[1]) == max(int(c.rsplit("-", 1)[1]) for c in after) + 1


def test_import_warns_and_leaves_unmatched_levels_and_requirements_unset(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Bundle Warn Co")
    built = _build_rich_project(client, token, org, project)
    bundle = _export(client, token, project["id"])

    def break_references(doc: dict) -> None:
        for risk in doc["risks"]:
            for ref in risk["levels"].values():
                if ref["name"] == "Catastrophic":
                    ref["name"] = "Apocalyptic"
            for treatment in risk["treatments"]:
                treatment["requirement_unique_code"] = "NOPE-999"
            if risk["type_name"] == "Cost":
                risk["type_name"] = "No such type"

    imported = _import(client, token, org["id"], _edit_bundle(bundle, break_references), "Risk Bundle Broken")
    warnings = imported["warnings"]
    assert any("Apocalyptic" in w and "left unset" in w for w in warnings)
    assert any("NOPE-999" in w and "skipped" in w for w in warnings)
    assert any("No such type" in w and "left untyped" in w for w in warnings)

    after = _risks(client, token, imported["project"]["id"])
    main = after[built["main"]["unique_code"]]
    assert main["inherent_rating"] is None  # an unmatched level leaves the risk "not rated", never silently re-rated
    assert main["effective_treatment_count"] == 0  # its link could not be matched, so its verdict is gone with it
    assert after[built["stale"]["unique_code"]]["risk_type_name"] is None


def test_a_duplicated_risk_code_in_a_bundle_is_skipped_with_a_warning(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Bundle Dup Co")
    create_risk(client, token, project["id"], title="Only one")
    bundle = _export(client, token, project["id"])
    imported = _import(
        client, token, org["id"], _edit_bundle(bundle, lambda doc: doc["risks"].append(dict(doc["risks"][0]))), "Risk Bundle Dup Reimport",
    )
    assert any("appears more than once" in w for w in imported["warnings"])
    assert [r["title"] for r in _risks(client, token, imported["project"]["id"]).values()] == ["Only one"]


def test_a_bundle_without_risks_imports_cleanly(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Bundle Empty Co")
    requirement = create_requirement(client, token, project["id"])
    assert requirement
    imported = _import(client, token, org["id"], _export(client, token, project["id"]), "Risk Bundle Empty Reimport")
    assert imported["warnings"] == []
    assert _risks(client, token, imported["project"]["id"]) == {}


def test_org_export_import_round_trips_risk_types_without_duplicating_seeds(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Bundle Org Co")
    h = auth_headers(token)
    created = client.post(f"/api/v1/orgs/{org['id']}/modules/risk_management/risk-types", json={"name": "Edge case"}, headers=h)
    assert created.status_code == 201, created.text
    risk = create_risk(client, token, project["id"], title="Org round trip", risk_type_id=None)
    assert risk["unique_code"]

    export = client.get(f"/api/v1/orgs/{org['id']}/export", headers=h)
    assert export.status_code == 200, export.text
    org_json = json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("org.json"))
    assert "Edge case" in [t["name"] for t in org_json["risk_types"]]

    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Risk Bundle Org Reimport"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    new_org_id = uuid.UUID(imported.json()["organization"]["id"])
    with SessionLocal() as db:
        names = [t.name for t in db.scalars(
            select(RiskTypeDefinition).where(RiskTypeDefinition.organization_id == new_org_id).order_by(RiskTypeDefinition.sort_order)
        )]
    assert len(names) == len(set(names)) and "Edge case" in names and "Safety" in names  # seeds and import do not double up
