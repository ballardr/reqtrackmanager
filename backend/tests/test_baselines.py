"""Tests for polymorphic baselines (`services.baseline`, `routers.projects.baselines`): a stage baseline still holds
requirements and now also what each enabled module's snapshot provider captures, a manual baseline needs no stage and
approves nothing, the permission and module gates, the project bundle round trip, and the table constraints.

A fake module registers the snapshot provider, so the hook is proven without any real module.
"""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.enums import BaselineKind
from app.models.requirement import Baseline, BaselineItem
from app.modules import registry as module_registry
from app.modules.registry import (
    BaselineSnapshotContext,
    BaselineSnapshotProvider,
    BaselineSnapshotRecord,
    ModuleDefinition,
    build_registry,
    get_baseline_snapshot_providers,
)
from app.services.permissions import encode_permission
from tests.conftest import auth_headers, create_component_and_category, create_org_user, create_project, login
from tests.stage_helpers import move_stage

FAKE_KEY = "baseline_fake"
WIDGET = "fake_widget"
WIDGET_IDS = [uuid.UUID("00000000-0000-0000-0000-0000000000a1"), uuid.UUID("00000000-0000-0000-0000-0000000000a2")]
SEEN: list[BaselineSnapshotContext] = []


def _snapshot(db, project, context):
    """The fake provider: two records, naming the project, and remembers the context it was called with."""
    SEEN.append(context)
    return [BaselineSnapshotRecord(item_id=i, content={"name": f"Widget {n}", "project": str(project.id)}) for n, i in enumerate(WIDGET_IDS, 1)]


@pytest.fixture
def fake_module():
    """Registers the fake module and its provider for one test, rebuilding the registry before and after."""
    SEEN.clear()
    module_registry.INSTALLED_MODULES.append(ModuleDefinition(
        key=FAKE_KEY, name="Baseline Fake", description="A fixture module for the baseline tests.", version="0.0.1",
        default_enabled=True, implemented=False, get_router=lambda: None, artefact_types=(WIDGET,),
        baseline_snapshots={WIDGET: BaselineSnapshotProvider(snapshot=_snapshot, permission=encode_permission(WIDGET, "manage"))},
    ))
    build_registry(force=True)
    yield FAKE_KEY
    module_registry.INSTALLED_MODULES[:] = [m for m in module_registry.INSTALLED_MODULES if m.key != FAKE_KEY]
    build_registry(force=True)


def _project_with_requirement(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Boot within 3s", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    )
    assert requirement.status_code == 201, requirement.text
    return project, requirement.json()


def _baselines(client, token, project_id) -> list[dict]:
    response = client.get(f"/api/v1/projects/{project_id}/baselines", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    return response.json()


def _member_token(client, admin_token, org_id, project_id, role: str, email: str) -> str:
    create_org_user(client, admin_token, org_id, email)
    users = client.get(f"/api/v1/orgs/{org_id}/users", headers=auth_headers(admin_token)).json()
    user_id = next(u["user_id"] for u in users if u["email"] == email)
    response = client.post(
        f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(admin_token),
    )
    assert response.status_code in (200, 201, 204), response.text
    return login(client, email, "Password123!")


def test_a_stage_baseline_holds_requirements_and_the_enabled_modules_records(client, admin_token, org_id, fake_module):
    project, requirement = _project_with_requirement(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    stage_id = client.get(f"/api/v1/projects/{project['id']}/stages", headers=headers).json()[0]["id"]
    assert move_stage(client, project["id"], stage_id, "approved", headers=headers).status_code == 200

    [baseline] = _baselines(client, admin_token, project["id"])
    assert baseline["kind"] == "stage" and baseline["stage_id"] == stage_id and baseline["stage_name"]
    assert baseline["item_counts"] == {"requirement": 1, WIDGET: 2}
    assert [(c.kind, str(c.stage_id) == stage_id, c.component_id) for c in SEEN] == [("stage", True, None)]

    with SessionLocal() as db:
        items = db.scalars(select(BaselineItem).where(BaselineItem.baseline_id == uuid.UUID(baseline["id"]))).all()
        by_type = {i.item_type: i for i in items if i.item_type == "requirement"}
        assert by_type["requirement"].item_id == by_type["requirement"].requirement_id == uuid.UUID(requirement["id"])
        widgets = sorted((i for i in items if i.item_type == WIDGET), key=lambda i: str(i.item_id))
        assert [w.item_id for w in widgets] == WIDGET_IDS
        assert widgets[0].snapshot == {"name": "Widget 1", "project": project["id"]}
        assert widgets[0].requirement_id is None and widgets[0].requirement_version_id is None


def test_a_manual_baseline_needs_no_stage_and_approves_nothing(client, admin_token, org_id, fake_module):
    project, requirement = _project_with_requirement(client, admin_token, org_id)
    headers = auth_headers(admin_token)

    created = client.post(f"/api/v1/projects/{project['id']}/baselines", json={"label": "  Before the review  "}, headers=headers)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["kind"] == "manual" and body["label"] == "Before the review"
    assert body["stage_id"] is None and body["stage_name"] is None and body["component_id"] is None
    assert body["item_counts"] == {"requirement": 1, WIDGET: 2}
    assert body["created_by_name"]
    assert [(c.kind, c.stage_id, c.component_id) for c in SEEN] == [("manual", None, None)]

    unchanged = client.get(f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}", headers=headers).json()
    assert unchanged["status"] == "draft"

    second = client.post(f"/api/v1/projects/{project['id']}/baselines", json={"label": "Second"}, headers=headers).json()
    assert [b["id"] for b in _baselines(client, admin_token, project["id"])] == [second["id"], body["id"]]


def test_a_manual_baseline_can_name_the_types_it_captures(client, admin_token, org_id, fake_module):
    project, _ = _project_with_requirement(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    only_module = client.post(
        f"/api/v1/projects/{project['id']}/baselines", json={"label": "Modules only", "item_types": [WIDGET]}, headers=headers,
    )
    assert only_module.status_code == 201, only_module.text
    assert only_module.json()["item_counts"] == {WIDGET: 2}

    only_requirements = client.post(
        f"/api/v1/projects/{project['id']}/baselines", json={"label": "Requirements", "item_types": ["requirement"]}, headers=headers,
    )
    assert only_requirements.json()["item_counts"] == {"requirement": 1}

    unknown = client.post(
        f"/api/v1/projects/{project['id']}/baselines", json={"label": "Bad", "item_types": ["no_such_type"]}, headers=headers,
    )
    assert unknown.status_code == 422
    blank = client.post(f"/api/v1/projects/{project['id']}/baselines", json={"label": "   "}, headers=headers)
    assert blank.status_code == 422


def test_a_manual_baseline_holds_only_what_the_person_may_snapshot(client, admin_token, org_id, fake_module):
    project, _ = _project_with_requirement(client, admin_token, org_id)
    member = _member_token(client, admin_token, org_id, project["id"], "member", "baseline-member@example.com")
    url = f"/api/v1/projects/{project['id']}/baselines"

    # A plain member sees the list but may snapshot nothing.
    assert _baselines(client, member, project["id"]) == []
    assert client.post(url, json={"label": "Nope"}, headers=auth_headers(member)).status_code == 403
    assert client.post(url, json={"label": "Nope", "item_types": [WIDGET]}, headers=auth_headers(member)).status_code == 403

    # A project manager may snapshot every type.
    manager = _member_token(client, admin_token, org_id, project["id"], "project_manager", "baseline-manager@example.com")
    assert client.post(url, json={"label": "Fine"}, headers=auth_headers(manager)).status_code == 201

    # Someone outside the project sees nothing and can take nothing.
    create_org_user(client, admin_token, org_id, "baseline-outsider@example.com")
    outsider = login(client, "baseline-outsider@example.com", "Password123!")
    assert client.get(url, headers=auth_headers(outsider)).status_code == 403
    assert client.post(url, json={"label": "Nope"}, headers=auth_headers(outsider)).status_code == 403


def test_a_module_that_is_off_for_the_organisation_is_not_captured(client, admin_token, org_id, fake_module):
    project, _ = _project_with_requirement(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    assert client.put(f"/api/v1/orgs/{org_id}/modules/{fake_module}", json={"enabled": False}, headers=headers).status_code == 200

    created = client.post(f"/api/v1/projects/{project['id']}/baselines", json={"label": "No module"}, headers=headers)
    assert created.status_code == 201, created.text
    assert created.json()["item_counts"] == {"requirement": 1}
    assert SEEN == []
    refused = client.post(
        f"/api/v1/projects/{project['id']}/baselines", json={"label": "Off", "item_types": [WIDGET]}, headers=headers,
    )
    assert refused.status_code == 403


def test_the_baseline_survives_a_project_bundle_round_trip(client, admin_token, org_id, fake_module):
    project, _ = _project_with_requirement(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    stage_id = client.get(f"/api/v1/projects/{project['id']}/stages", headers=headers).json()[0]["id"]
    assert move_stage(client, project["id"], stage_id, "approved", headers=headers).status_code == 200
    client.post(f"/api/v1/projects/{project['id']}/baselines", json={"label": "Manual one"}, headers=headers)

    exported = client.get(f"/api/v1/projects/{project['id']}/export", headers=headers)
    assert exported.status_code == 200
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": "Copy"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=headers,
    )
    assert imported.status_code == 201, imported.text
    new_id = imported.json()["project"]["id"]

    copy = {b["label"]: b for b in _baselines(client, admin_token, new_id)}
    original = {b["label"]: b for b in _baselines(client, admin_token, project["id"])}
    assert set(copy) == set(original) and len(copy) == 2
    for label, baseline in copy.items():
        assert baseline["kind"] == original[label]["kind"]
        assert baseline["item_counts"] == original[label]["item_counts"] == {"requirement": 1, WIDGET: 2}
    assert copy["Manual one"]["stage_id"] is None and copy["Manual one"]["stage_name"] is None

    with SessionLocal() as db:
        widgets = db.scalars(
            select(BaselineItem).join(Baseline, Baseline.id == BaselineItem.baseline_id)
            .where(Baseline.project_id == uuid.UUID(new_id), BaselineItem.item_type == WIDGET)
        ).all()
        assert len(widgets) == 4
        # The live record has another id in the copy, so none is claimed; the snapshot is kept as taken.
        assert all(w.item_id is None for w in widgets)
        assert {w.snapshot["name"] for w in widgets} == {"Widget 1", "Widget 2"}


def test_a_captured_type_this_installation_does_not_register_is_skipped_with_a_warning(client, admin_token, org_id, fake_module):
    project, _ = _project_with_requirement(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    client.post(f"/api/v1/projects/{project['id']}/baselines", json={"label": "Manual one"}, headers=headers)
    exported = client.get(f"/api/v1/projects/{project['id']}/export", headers=headers)

    # The module is gone when the bundle is imported (another installation).
    module_registry.INSTALLED_MODULES[:] = [m for m in module_registry.INSTALLED_MODULES if m.key != FAKE_KEY]
    build_registry(force=True)
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": "Copy"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=headers,
    )
    assert imported.status_code == 201, imported.text
    assert sum("was skipped" in w for w in imported.json()["warnings"]) == 2
    [baseline] = _baselines(client, admin_token, imported.json()["project"]["id"])
    assert baseline["item_counts"] == {"requirement": 1}


def test_the_table_constraints_keep_the_shapes_apart(client, admin_token, org_id):
    project, requirement = _project_with_requirement(client, admin_token, org_id)
    stage_id = client.get(f"/api/v1/projects/{project['id']}/stages", headers=auth_headers(admin_token)).json()[0]["id"]
    admin_id = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()["id"]
    project_uuid = uuid.UUID(project["id"])

    def add_baseline(db, **fields) -> Baseline:
        baseline = Baseline(project_id=project_uuid, label="x", created_by=uuid.UUID(admin_id), **fields)
        db.add(baseline)
        db.flush()
        return baseline

    with SessionLocal() as db:
        with pytest.raises(IntegrityError):
            add_baseline(db, kind=BaselineKind.MANUAL, stage_id=uuid.UUID(stage_id))
        db.rollback()
        with pytest.raises(IntegrityError):
            add_baseline(db, kind=BaselineKind.STAGE)
        db.rollback()

        manual = add_baseline(db, kind=BaselineKind.MANUAL)
        # A module item needs a snapshot and no requirement columns; a requirement item needs both of its columns.
        db.add(BaselineItem(baseline_id=manual.id, item_type=WIDGET, item_id=WIDGET_IDS[0]))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
        manual = add_baseline(db, kind=BaselineKind.MANUAL)
        db.add(BaselineItem(baseline_id=manual.id, item_type="requirement", item_id=uuid.UUID(requirement["id"])))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

        manual = add_baseline(db, kind=BaselineKind.MANUAL)
        db.add(BaselineItem(baseline_id=manual.id, item_type=WIDGET, item_id=WIDGET_IDS[0], snapshot={"a": 1}))
        db.flush()
        db.add(BaselineItem(baseline_id=manual.id, item_type=WIDGET, item_id=WIDGET_IDS[0], snapshot={"a": 2}))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
        db.execute(text("SELECT 1"))


def test_every_snapshot_provider_names_a_type_its_module_declares(fake_module):
    providers = get_baseline_snapshot_providers()
    assert WIDGET in providers
    registry = module_registry.get_module_registry()
    for artefact_type, (module_key, provider) in providers.items():
        assert artefact_type in registry[module_key].artefact_types, f"{module_key} snapshots an undeclared type"
        assert provider.permission.startswith(f"{artefact_type}:"), f"{artefact_type} needs its own permission atom"
