"""Every code path that writes the next version of a versioned record takes the
record's row lock *before* reading the current version.

A versioned edit closes the current version and inserts the next, so two
unserialised edits both read version N and the loser dies on the
`(record, version_number)` unique constraint with a 500. The lock makes the
second edit wait, then apply on top of the first.

Two layers:
- a structural scan of `app/`: every call to an `apply_*new_version` function
  must be preceded, in the same function, by a lock call, or the function must
  be a helper whose every caller is (recursively). A future versioned type that
  forgets the lock fails here without needing its own test.
- behavioural: for the core requirement and the Context & Strategy types, an
  edit made while another transaction holds the row lock blocks, then applies.
"""

from __future__ import annotations

import ast
import re
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select

from app.database import SessionLocal
from app.models.requirement import Requirement, RequirementVersion
from app.modules.context_strategy.models import (
    FutureState,
    FutureStateVersion,
    GuidingPrinciple,
    GuidingPrincipleVersion,
    Strategy,
    StrategyVersion,
)
from app.modules.context_strategy.tests.test_context_strategy_api import _PAYLOAD as STRATEGY_PAYLOAD
from app.modules.context_strategy.tests.test_context_strategy_future_state_api import _PAYLOAD as FUTURE_STATE_PAYLOAD
from app.modules.context_strategy.tests.test_context_strategy_guiding_principle_api import (
    _PAYLOAD as GUIDING_PRINCIPLE_PAYLOAD,
)
from app.modules.risk_management.models import Risk, RiskVersion
from app.modules.stakeholders.models import (
    Persona,
    PersonaVersion,
    Stakeholder,
    StakeholderNeed,
    StakeholderNeedVersion,
    StakeholderVersion,
)
from tests.conftest import auth_headers
from tests.link_world import World

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
_APPLY = re.compile(r"^apply_\w*new_version$")
_ROUTE_METHODS = {"get", "post", "put", "patch", "delete"}
# Creating a record and activating it in one request writes a version of a row no other transaction can
# see yet, so there is nothing to serialise against. A new versioned type with that shortcut adds its
# creator here, which is the visible, reviewable act.
_FRESH_ROW_CREATORS = {"create_persona", "create_stakeholder", "create_need"}


def _call_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_lock(name: str | None) -> bool:
    """`lock_row_for_update` or a `get_current_*_for_update` style getter."""
    return bool(name) and name != "with_for_update" and name.endswith("_for_update")


def _is_route(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in _ROUTE_METHODS
        for d in fn.decorator_list
    )


def _functions() -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    found = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        rel = path.relative_to(APP_ROOT).as_posix()
        if "/tests/" in f"/{rel}" or "/migrations/" in f"/{rel}":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                found.append((rel, node))
    return found


def _calls(fn: ast.AST) -> list[tuple[str, int]]:
    """Every (name, line) the function calls or passes by name as an argument
    (`apply_value_error_as_conflict(propose_strategy, ...)`)."""
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name:
                out.append((name, node.lineno))
            out.extend((a.id, a.lineno) for a in node.args if isinstance(a, ast.Name))
    return out


def find_unlocked_version_writers() -> list[str]:
    """Functions that reach an `apply_*new_version` call without locking first
    and that no locking caller covers."""
    functions = _functions()
    reaching = {name for _, fn in functions if _APPLY.match(fn.name) for name in [fn.name]}
    violations: dict[tuple[str, str], int] = {}
    delegates: set[str] = set()
    changed = True
    while changed:
        changed = False
        for rel, fn in functions:
            if _APPLY.match(fn.name):
                continue
            calls = _calls(fn)
            hits = [line for name, line in calls if name in reaching]
            if not hits:
                continue
            locks = [line for name, line in calls if _is_lock(name) or name in _FRESH_ROW_CREATORS]
            if locks and min(locks) < min(hits):
                continue
            if _is_route(fn):
                if (rel, fn.name) not in violations:
                    violations[(rel, fn.name)] = fn.lineno
                continue
            if fn.name not in reaching:
                reaching.add(fn.name)
                delegates.add(fn.name)
                changed = True
    # A delegate that nothing calls (or that only unlocked, non-route code calls) is a violation too:
    called = {name for _, fn in functions for name, _ in _calls(fn)}
    for rel, fn in functions:
        if fn.name in delegates and fn.name not in called:
            violations[(rel, fn.name)] = fn.lineno
    return [f"{rel}:{line} {name}" for (rel, name), line in sorted(violations.items())]


def test_every_version_writer_locks_the_record_before_reading_its_current_version():
    assert find_unlocked_version_writers() == []


def test_the_scan_catches_a_writer_without_a_lock(tmp_path, monkeypatch):
    """The scan itself must fail on the defect it guards against."""
    source = (
        "def apply_widget_new_version(db, w, v):\n    pass\n\n"
        "@router.put('/w')\ndef update_widget(db):\n    v = get_current(db)\n    apply_widget_new_version(db, 1, v)\n"
    )
    package = tmp_path / "app"
    package.mkdir()
    (package / "widgets.py").write_text(source)
    monkeypatch.setitem(globals(), "APP_ROOT", package)
    assert find_unlocked_version_writers() == ["widgets.py:5 update_widget"]


def _commit_competing_version(session, version_model, fk_name: str, row_id: uuid.UUID) -> None:
    """Does what a concurrent edit that won the race does: closes the current version and
    inserts the next one, copying every column the edit does not change."""
    current = session.scalar(
        select(version_model).where(getattr(version_model, fk_name) == row_id, version_model.valid_to.is_(None))
    )
    now = datetime.now(UTC)
    columns = {c.key: getattr(current, c.key) for c in sa_inspect(version_model).mapper.column_attrs if c.key != "id"}
    current.valid_to = now
    session.flush()
    session.add(version_model(**{**columns, "version_number": current.version_number + 1, "valid_from": now, "valid_to": None}))
    session.commit()


def _race_a_concurrent_edit(model, version_model, fk_name: str, row_id: str, send):
    """Runs `send()` (a request that writes the next version of `row_id`) against a competitor.

    Another transaction holds the row lock, the request starts and must wait, and the competitor
    then commits its own next version. A request that had read the current version before
    waiting would insert a duplicate `(record, version_number)` and fail with a 500; one that
    locks first reads the competitor's version and writes the one after it. (Blocking alone
    proves nothing: inserting a version row waits on the lock through its foreign key anyway.)
    """
    result: dict = {}
    worker = threading.Thread(target=lambda: result.update(response=send()))
    with SessionLocal() as holder:
        holder.execute(select(model.id).where(model.id == uuid.UUID(row_id)).with_for_update())
        worker.start()
        worker.join(timeout=2)
        assert worker.is_alive(), "the request finished while another transaction held the row lock"
        _commit_competing_version(holder, version_model, fk_name, uuid.UUID(row_id))
    worker.join(timeout=30)
    return result["response"]


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Version Lock Org", context_strategy=True)


def _raced(world: World, model, version_model, fk_name: str, row_id: str, method: str, url: str, body: dict | None):
    """The response of a request raced against a competing edit; it must succeed."""
    headers = auth_headers(world.token)
    response = _race_a_concurrent_edit(
        model, version_model, fk_name, row_id, lambda: world.client.request(method, url, json=body, headers=headers),
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


def test_a_requirement_edit_applies_on_top_of_a_concurrent_edit(world):
    project = world.project()
    req = world.requirement(project, "Lock target")
    url = f"/api/v1/projects/{project['id']}/requirements/{req}"
    current = world.client.get(url, headers=auth_headers(world.token)).json()
    body = {
        "name": "Edited under lock", "component_id": current["component_id"], "category_id": current["category_id"],
        "owner": current["owner"],
    }
    edited = _raced(world, Requirement, RequirementVersion, "requirement_id", str(req), "PUT", url, body)
    assert edited["name"] == "Edited under lock"
    history = world.client.get(f"{url}/history", headers=auth_headers(world.token)).json()
    assert sorted(v["version_number"] for v in history) == [1, 2, 3]


def test_a_requirement_approval_applies_on_top_of_a_concurrent_edit(world):
    project = world.project()
    req = world.requirement(project, "Approve under lock")
    url = f"/api/v1/projects/{project['id']}/requirements/{req}"
    approved = _raced(world, Requirement, RequirementVersion, "requirement_id", str(req), "POST", f"{url}/approve", None)
    assert approved["status"] == "approved"
    history = world.client.get(f"{url}/history", headers=auth_headers(world.token)).json()
    assert sorted(v["version_number"] for v in history) == [1, 2, 3]


@pytest.mark.parametrize(
    ("collection", "model", "version_model", "fk_name", "payload", "field"),
    [
        ("strategies", Strategy, StrategyVersion, "strategy_id", STRATEGY_PAYLOAD, "title"),
        ("future-states", FutureState, FutureStateVersion, "future_state_id", FUTURE_STATE_PAYLOAD, "title"),
        (
            "guiding-principles", GuidingPrinciple, GuidingPrincipleVersion, "guiding_principle_id",
            GUIDING_PRINCIPLE_PAYLOAD, "name",
        ),
    ],
)
def test_a_context_strategy_edit_and_transition_apply_on_top_of_a_concurrent_edit(
    world, collection, model, version_model, fk_name, payload, field,
):
    project = world.project()
    base = f"/api/v1/projects/{project['id']}/modules/context_strategy/{collection}"
    created = world.client.post(base, json=payload, headers=auth_headers(world.token))
    assert created.status_code == 201, created.text
    record = created.json()

    edited = _raced(
        world, model, version_model, fk_name, record["id"], "PUT", f"{base}/{record['id']}",
        {**payload, field: "Edited under lock"},
    )
    assert edited[field] == "Edited under lock"
    assert edited["version_number"] == 3

    proposed = _raced(world, model, version_model, fk_name, record["id"], "POST", f"{base}/{record['id']}/propose", None)
    assert proposed["version_number"] == 5
    assert proposed["status"] == "proposed"


@pytest.mark.parametrize(
    ("collection", "model", "version_model", "fk_name", "payload"),
    [
        ("personas", Persona, PersonaVersion, "persona_id", {"name": "Field Technician", "description": "Inspects equipment."}),
        ("stakeholders", Stakeholder, StakeholderVersion, "stakeholder_id", {"name": "Pat Regulator", "description": "Audits."}),
        ("needs", StakeholderNeed, StakeholderNeedVersion, "need_id", {"name": "Diagnose faults", "description": "Quickly."}),
    ],
)
def test_a_stakeholders_edit_applies_on_top_of_a_concurrent_edit(world, collection, model, version_model, fk_name, payload):
    world.enable("stakeholders")
    project = world.project()
    base = f"/api/v1/projects/{project['id']}/modules/stakeholders/{collection}"
    created = world.client.post(base, json=payload, headers=auth_headers(world.token))
    assert created.status_code == 201, created.text
    record = created.json()

    edited = _raced(
        world, model, version_model, fk_name, record["id"], "PUT", f"{base}/{record['id']}",
        {"description": "Edited under lock"},
    )
    assert edited["description"] == "Edited under lock"
    assert edited["version_number"] == 3


def test_a_risk_edit_applies_on_top_of_a_concurrent_edit(client, admin_token):
    from app.modules.risk_management.tests._helpers import create_risk, project_base, setup

    _, project, token = setup(client, admin_token, "Risk Race Co")
    risk = create_risk(client, token, project["id"])
    world = SimpleNamespace(client=client, token=token)
    edited = _raced(
        world, Risk, RiskVersion, "risk_id", risk["id"], "PUT", f"{project_base(project['id'])}/risks/{risk['id']}",
        {"cause": "Edited under lock"},
    )
    assert edited["cause"] == "Edited under lock"
    assert edited["version_number"] == 3
