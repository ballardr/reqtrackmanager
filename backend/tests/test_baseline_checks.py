"""Tests for the core baseline check seam (`services.baseline`, the `GovernanceSeam.BASELINE` policy and the
`BaselineCheckProvider` hook) with a fake module and no Governance module: no check runs by default, a failing check refuses
the whole baseline with every failure listed and nothing approved or stored, the module records are captured once and
reused, a policy's baseline kinds choose which baselines it guards, the preview writes nothing, and the review-deadline sweep
leaves a refused stage in review and tells its managers once.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.project import Project
from app.models.requirement import Baseline
from app.models.user import User
from app.modules import registry as module_registry
from app.modules.registry import (
    BaselineSnapshotContext,
    BaselineSnapshotProvider,
    BaselineSnapshotRecord,
    ModuleDefinition,
    build_registry,
)
from app.modules.seams import (
    BaselineCheckContext,
    BaselineCheckFailure,
    BaselineCheckProvider,
    BaselinePolicy,
    GovernanceSeam,
    PolicyResolver,
)
from app.services import baseline as baseline_service
from app.services.permissions import encode_permission
from app.services.stages import auto_approve_overdue_stage_reviews
from tests.conftest import auth_headers, create_component_and_category, create_project
from tests.stage_helpers import move_stage

FAKE_KEY = "baseline_check_fake"
WIDGET = "check_widget"
WIDGET_IDS = [uuid.UUID("00000000-0000-0000-0000-0000000000b1"), uuid.UUID("00000000-0000-0000-0000-0000000000b2")]
CHECK = f"{FAKE_KEY}:widgets_complete"
SNAPSHOTS: list[str] = []
POLICY: dict[str, tuple[str, ...]] = {"stage": (), "manual": ()}
NOTIFY = [True]
BAD_REQUIREMENTS: set[uuid.UUID] = set()
WIDGETS_FAIL = [True]


def _snapshot(db, project, context: BaselineSnapshotContext):
    """Two widgets; remembers each call so a test can see the records were captured once."""
    SNAPSHOTS.append(context.kind)
    return [BaselineSnapshotRecord(item_id=i, content={"name": f"Widget {n}"}) for n, i in enumerate(WIDGET_IDS, 1)]


def _check(db, context: BaselineCheckContext, record_ids):
    """Fails every widget and every requirement a test marked bad."""
    failures = [
        BaselineCheckFailure(WIDGET, i, "widgets_complete", "The widget is incomplete.", code=f"WID-00{n}")
        for n, i in enumerate(record_ids.get(WIDGET, ()), 1) if WIDGETS_FAIL[0]
    ]
    failures += [
        BaselineCheckFailure("requirement", i, "widgets_complete", "The requirement is marked bad.", code="REQ-BAD")
        for i in record_ids.get("requirement", ()) if i in BAD_REQUIREMENTS
    ]
    return failures


def _policy(db, project_id):
    stage, manual = POLICY["stage"], POLICY["manual"]
    return BaselinePolicy(stage_checks=stage, manual_checks=manual, notify_managers=NOTIFY[0]) if stage or manual else None


@pytest.fixture
def fake_module():
    SNAPSHOTS.clear()
    BAD_REQUIREMENTS.clear()
    WIDGETS_FAIL[0] = True
    NOTIFY[0] = True
    POLICY.update(stage=(), manual=())
    module_registry.INSTALLED_MODULES.append(ModuleDefinition(
        key=FAKE_KEY, name="Baseline Check Fake", description="A fixture module for the baseline check tests.", version="0.0.1",
        default_enabled=True, implemented=False, get_router=lambda: None, artefact_types=(WIDGET,),
        baseline_snapshots={WIDGET: BaselineSnapshotProvider(snapshot=_snapshot, permission=encode_permission(WIDGET, "manage"))},
        baseline_check_providers=(
            BaselineCheckProvider(key="widgets_complete", name="Widgets complete", artefact_types=(WIDGET, "requirement"), check=_check),
        ),
        policy_resolvers=(PolicyResolver(seam=GovernanceSeam.BASELINE, resolve_project=_policy),),
    ))
    build_registry(force=True)
    yield
    module_registry.INSTALLED_MODULES[:] = [m for m in module_registry.INSTALLED_MODULES if m.key != FAKE_KEY]
    build_registry(force=True)


def _project(client, admin_token, org_id, name="Check Project"):
    project = create_project(client, admin_token, org_id, name)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Boot within 3s", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    )
    assert requirement.status_code == 201, requirement.text
    return project, requirement.json()


def _stage_id(client, token, project_id) -> str:
    return client.get(f"/api/v1/projects/{project_id}/stages", headers=auth_headers(token)).json()[0]["id"]


def _baseline_count(project_id: str) -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(Baseline).where(Baseline.project_id == uuid.UUID(project_id))) or 0


def _requirement_status(client, token, project_id, requirement_id) -> str:
    return client.get(f"/api/v1/projects/{project_id}/requirements/{requirement_id}", headers=auth_headers(token)).json()["status"]


def _stage_phase(client, token, project_id, stage_id) -> str:
    stages = client.get(f"/api/v1/projects/{project_id}/stages", headers=auth_headers(token)).json()
    return next(s for s in stages if s["id"] == stage_id)["phase_name"]


# --- the default ----------------------------------------------------------------------------------


def test_no_check_runs_when_no_policy_enables_one(client, admin_token, org_id, fake_module):
    project, requirement = _project(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    assert client.post(f"/api/v1/projects/{project['id']}/baselines", json={"label": "Manual"}, headers=headers).status_code == 201
    assert move_stage(client, project["id"], _stage_id(client, admin_token, project["id"]), "approved", headers=headers).status_code == 200
    assert _requirement_status(client, admin_token, project["id"], requirement["id"]) == "approved"
    assert SNAPSHOTS == ["manual", "stage"]  # one capture per baseline, no extra read for the checks


# --- a stage baseline ----------------------------------------------------------------------------


def test_a_failing_check_refuses_the_whole_stage_baseline_and_lists_every_failure(client, admin_token, org_id, fake_module):
    project, requirement = _project(client, admin_token, org_id)
    BAD_REQUIREMENTS.add(uuid.UUID(requirement["id"]))
    POLICY["stage"] = (CHECK,)
    headers = auth_headers(admin_token)
    stage_id = _stage_id(client, admin_token, project["id"])
    before = _stage_phase(client, admin_token, project["id"], stage_id)

    refused = move_stage(client, project["id"], stage_id, "approved", headers=headers)
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["message"].startswith("The baseline was refused: 3 records failed 1 baseline check.")
    assert [(f["artefact_type"], f["code"], f["check_name"]) for f in detail["failures"]] == [
        (WIDGET, "WID-001", "Widgets complete"), (WIDGET, "WID-002", "Widgets complete"), ("requirement", "REQ-BAD", "Widgets complete"),
    ]
    assert detail["failures"][0]["check_key"] == CHECK
    # Nothing was approved, locked or stored.
    assert _requirement_status(client, admin_token, project["id"], requirement["id"]) == "draft"
    assert _stage_phase(client, admin_token, project["id"], stage_id) == before
    assert _baseline_count(project["id"]) == 0
    assert SNAPSHOTS == ["stage"]

    # The same baseline is written once the failures are fixed, and the records the checks read are the ones it stores.
    BAD_REQUIREMENTS.clear()
    WIDGETS_FAIL[0] = False
    assert move_stage(client, project["id"], stage_id, "approved", headers=headers).status_code == 200
    assert _requirement_status(client, admin_token, project["id"], requirement["id"]) == "approved"
    assert SNAPSHOTS == ["stage", "stage"]
    [baseline] = client.get(f"/api/v1/projects/{project['id']}/baselines", headers=headers).json()
    assert baseline["item_counts"] == {"requirement": 1, WIDGET: 2}


def test_a_policy_guards_only_the_baseline_kinds_it_names(client, admin_token, org_id, fake_module):
    project, _ = _project(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    POLICY.update(stage=(CHECK,), manual=())
    assert client.post(f"/api/v1/projects/{project['id']}/baselines", json={"label": "Manual"}, headers=headers).status_code == 201
    POLICY.update(stage=(), manual=(CHECK,))
    refused = client.post(f"/api/v1/projects/{project['id']}/baselines", json={"label": "Refused"}, headers=headers)
    assert refused.status_code == 409
    assert {f["code"] for f in refused.json()["detail"]["failures"]} == {"WID-001", "WID-002"}
    assert _baseline_count(project["id"]) == 1
    assert move_stage(client, project["id"], _stage_id(client, admin_token, project["id"]), "approved", headers=headers).status_code == 200


def test_the_preview_runs_the_same_checks_and_writes_nothing(client, admin_token, org_id, fake_module):
    project, requirement = _project(client, admin_token, org_id)
    BAD_REQUIREMENTS.add(uuid.UUID(requirement["id"]))
    POLICY.update(stage=(CHECK,), manual=(CHECK,))
    stage_id = _stage_id(client, admin_token, project["id"])
    with SessionLocal() as db:
        db_project = db.get(Project, uuid.UUID(project["id"]))
        user = db.scalars(select(User).where(User.email == "admin@example.com")).first()
        assert db_project is not None and user is not None
        checks, failures = baseline_service.preview_checks(db, db_project, user, "stage", stage_id=uuid.UUID(stage_id))
        assert [k for k, _ in checks] == [CHECK] and len(failures) == 3
        _, manual = baseline_service.preview_checks(db, db_project, user, "manual")
        assert len(manual) == 3
        with pytest.raises(ValueError, match="stage"):
            baseline_service.preview_checks(db, db_project, user, "stage")
        POLICY.update(stage=(), manual=())
        assert baseline_service.preview_checks(db, db_project, user, "manual") == ([], [])
    assert _baseline_count(project["id"]) == 0


# --- the review-deadline sweep ---------------------------------------------------------------------


def _in_review_past_deadline(client, admin_token, project_id) -> str:
    stage_id = _stage_id(client, admin_token, project_id)
    headers = auth_headers(admin_token)
    assert move_stage(client, project_id, stage_id, "review", headers=headers).status_code == 200
    resp = client.post(
        f"/api/v1/projects/{project_id}/stages/{stage_id}/review-deadline",
        json={"review_deadline": (datetime.now(UTC) - timedelta(days=1)).isoformat()}, headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return stage_id


def _sweep() -> None:
    with SessionLocal() as db:
        auto_approve_overdue_stage_reviews(db)


def _refusal_notices(client, token) -> list[dict]:
    rows = client.get("/api/v1/notifications", headers=auth_headers(token)).json()
    return [r for r in rows if r["type"] == "stage_baseline_refused"]


def test_the_sweep_leaves_a_refused_stage_in_review_and_tells_the_managers_once(client, admin_token, org_id, fake_module):
    project, requirement = _project(client, admin_token, org_id)
    BAD_REQUIREMENTS.add(uuid.UUID(requirement["id"]))
    POLICY["stage"] = (CHECK,)
    stage_id = _in_review_past_deadline(client, admin_token, project["id"])

    _sweep()
    assert _stage_phase(client, admin_token, project["id"], stage_id) == "Review"
    assert _requirement_status(client, admin_token, project["id"], requirement["id"]) == "draft"
    assert _baseline_count(project["id"]) == 0
    [notice] = _refusal_notices(client, admin_token)
    assert notice["entity_id"] == stage_id
    assert "WID-001" in notice["body"] and "The widget is incomplete." in notice["body"]

    _sweep()  # the daily retry stays silent while the failures are the same
    assert len(_refusal_notices(client, admin_token)) == 1

    POLICY["stage"] = ()
    _sweep()
    assert _stage_phase(client, admin_token, project["id"], stage_id) == "Approved"
    assert _requirement_status(client, admin_token, project["id"], requirement["id"]) == "approved"


def test_the_sweep_stays_silent_when_the_policy_does_not_notify_managers(client, admin_token, org_id, fake_module):
    project, requirement = _project(client, admin_token, org_id, "Silent Sweep Project")
    BAD_REQUIREMENTS.add(uuid.UUID(requirement["id"]))
    POLICY["stage"] = (CHECK,)
    NOTIFY[0] = False
    stage_id = _in_review_past_deadline(client, admin_token, project["id"])

    _sweep()
    assert _stage_phase(client, admin_token, project["id"], stage_id) == "Review"
    assert _refusal_notices(client, admin_token) == []

    NOTIFY[0] = True
    _sweep()
    assert len(_refusal_notices(client, admin_token)) == 1


def test_the_sweep_skips_a_stage_the_approval_rules_refuse_and_still_runs_the_others(client, admin_token, org_id):
    project, _ = _project(client, admin_token, org_id, "Separation Sweep Project")
    other, other_requirement = _project(client, admin_token, org_id, "Other Sweep Project")
    headers = auth_headers(admin_token)
    # A separate approver is required and the only manager created the requirement, so approval is refused.
    resp = client.put(
        f"/api/v1/projects/{project['id']}/approval-separation/requirement", json={"separate_approver": True}, headers=headers,
    )
    assert resp.status_code == 200, resp.text
    stuck = _in_review_past_deadline(client, admin_token, project["id"])
    free = _in_review_past_deadline(client, admin_token, other["id"])
    _sweep()
    assert _stage_phase(client, admin_token, project["id"], stuck) == "Review"
    assert _stage_phase(client, admin_token, other["id"], free) == "Approved"
    assert _requirement_status(client, admin_token, other["id"], other_requirement["id"]) == "approved"
