"""Tests for Decision Management's two seeding hooks (docs/plans/module-04-
decision-management-plan.md Phase 1):

- `app.modules.decisions.module._seed_new_project` (`on_project_created`)
  — every new project gets the 5 default `DecisionTypeDefinition` rows,
  unconditionally, mirroring `app.modules.compliance`'s own `on_org_
  created` seeding test one lifecycle event later.
- `app.modules.decisions.module._seed_org_templates` (`on_org_created_
  with_choices`) — a new organisation gets a `DecisionTemplateDefinition`
  row per selected ADR template pack, opt-in (Phase 0 addendum Q1) rather
  than unconditional, exercised end-to-end through the real `POST /orgs`
  endpoint's `module_choice_keys` field.

No HTTP endpoint exists yet for either `DecisionTypeDefinition` or
`DecisionTemplateDefinition` (Phase 1 is data model only — Phase 4 adds
the API), so these assert by querying the database directly, the same
"data-model-only phase, test through the DB" approach `test_module_
registry.py` uses for the generic hook-dispatch mechanism itself.
"""

from __future__ import annotations

from app.database import SessionLocal
from app.modules.decisions.models import DecisionTemplateDefinition, DecisionTypeDefinition
from app.modules.decisions.service import DECISION_TEMPLATE_PACKS, DEFAULT_DECISION_TYPES
from tests.conftest import auth_headers, create_org_admin_in, create_project


def _decision_type_names(project_id: str) -> set[str]:
    db = SessionLocal()
    try:
        rows = db.query(DecisionTypeDefinition.name).filter(DecisionTypeDefinition.project_id == project_id).all()
    finally:
        db.close()
    return {name for (name,) in rows}


def _decision_template_names(organization_id: str) -> set[str]:
    db = SessionLocal()
    try:
        rows = db.query(DecisionTemplateDefinition.name).filter(
            DecisionTemplateDefinition.organization_id == organization_id
        ).all()
    finally:
        db.close()
    return {name for (name,) in rows}


def test_creating_a_project_seeds_default_decision_types(client, admin_token):
    # I-M-05 removed the server-admin bypass from `require_org_role` — the
    # bootstrap server admin can't create a project in an org it merely
    # created, only a genuine member of that org can (`create_org_admin_in`,
    # mirroring every other cross-org test in this codebase).
    org, org_admin_token = create_org_admin_in(client, admin_token, "Decision Types Seeding Test Co")
    project = create_project(client, org_admin_token, org["id"], "Decision Types Seeding Test Project")

    assert _decision_type_names(project["id"]) == set(DEFAULT_DECISION_TYPES)


def test_creating_an_org_with_no_module_choice_keys_field_seeds_every_default_template(client, admin_token):
    resp = client.post(
        "/api/v1/orgs", json={"name": "Decision Templates Default Seeding Co"}, headers=auth_headers(admin_token)
    )
    assert resp.status_code == 201, resp.text
    org_id = resp.json()["id"]

    assert _decision_template_names(org_id) == {pack.name for pack in DECISION_TEMPLATE_PACKS}


def test_creating_an_org_with_empty_module_choice_keys_seeds_no_templates(client, admin_token):
    resp = client.post(
        "/api/v1/orgs",
        json={"name": "Decision Templates Opt-Out Co", "module_choice_keys": []},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    org_id = resp.json()["id"]

    assert _decision_template_names(org_id) == set()


def test_creating_an_org_with_one_module_choice_key_seeds_only_that_template(client, admin_token):
    madr_pack = next(pack for pack in DECISION_TEMPLATE_PACKS if "MADR" in pack.name)
    resp = client.post(
        "/api/v1/orgs",
        json={"name": "Decision Templates Partial Seeding Co", "module_choice_keys": [madr_pack.choice_key]},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    org_id = resp.json()["id"]

    assert _decision_template_names(org_id) == {madr_pack.name}


def test_org_creation_choices_endpoint_lists_the_three_template_packs(client, admin_token):
    resp = client.get("/api/v1/orgs/creation-choices", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    keys = {option["key"] for option in resp.json()}
    assert keys >= {pack.choice_key for pack in DECISION_TEMPLATE_PACKS}
