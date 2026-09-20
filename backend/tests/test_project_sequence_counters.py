"""Tests for the generic per-project sequence counter (Module 0 — Platform
Foundations, Phase 2): `app.models.sequence.ProjectSequenceCounter` and
`app.services.sequences`.

Per the plan's own verification bar: confirms codes are never reused
across artefact types sharing one project (each `(project, artefact_type)`
pair gets its own counter, not a shared one), and that concurrent creation
of two artefacts of the same type in the same project never produces a
duplicate code.
"""

import threading
from uuid import UUID

from app.database import SessionLocal
from app.models.enums import ArtefactType
from app.models.project import Project
from app.services import sequences
from tests.conftest import create_org_admin_in, create_project


def test_codes_start_at_one_and_advance_per_project_and_type(client, admin_token):
    """Two calls for the same `(project, artefact_type)` advance
    sequentially; a different artefact type in the same project gets its
    own counter starting at 1, not a continuation of the first type's."""
    org, token = create_org_admin_in(client, admin_token, "Sequence Counter Org")
    project = create_project(client, token, org["id"])
    project_id = UUID(project["id"])

    db = SessionLocal()
    try:
        proj = db.get(Project, project_id)
        first = sequences.generate_unique_code(db, proj, ArtefactType.REQUIREMENT, "REQ")
        second = sequences.generate_unique_code(db, proj, ArtefactType.REQUIREMENT, "REQ")
        other_type_first = sequences.generate_unique_code(db, proj, ArtefactType.REQUIREMENT_ACTION, "ACT")
        db.commit()
    finally:
        db.close()

    assert first == "REQ-001"
    assert second == "REQ-002"
    assert other_type_first == "ACT-001"


def test_codes_are_scoped_per_project_not_shared_across_projects(client, admin_token):
    """The same artefact type in two different projects each starts its
    own counter at 1 — a `ProjectSequenceCounter` row is per `project_id`,
    not global."""
    org, token = create_org_admin_in(client, admin_token, "Sequence Counter Org 2")
    project_a = create_project(client, token, org["id"], "Project A")
    project_b = create_project(client, token, org["id"], "Project B")

    db = SessionLocal()
    try:
        proj_a = db.get(Project, UUID(project_a["id"]))
        proj_b = db.get(Project, UUID(project_b["id"]))
        code_a = sequences.generate_unique_code(db, proj_a, ArtefactType.REQUIREMENT, "REQ")
        code_b = sequences.generate_unique_code(db, proj_b, ArtefactType.REQUIREMENT, "REQ")
        db.commit()
    finally:
        db.close()

    assert code_a == "REQ-001"
    assert code_b == "REQ-001"


def test_concurrent_generation_never_produces_duplicate_codes(client, admin_token):
    """Two real, overlapping transactions each generating a code for the
    same `(project, artefact_type)` at the same time must still get
    distinct, sequential codes — proving `_next_sequence`'s project-row
    lock actually serializes them, not just that sequential calls happen
    to work."""
    org, token = create_org_admin_in(client, admin_token, "Sequence Counter Concurrency Org")
    project = create_project(client, token, org["id"])
    project_id = UUID(project["id"])

    barrier = threading.Barrier(2)
    codes: list[str] = []
    codes_lock = threading.Lock()
    errors: list[BaseException] = []

    def worker():
        db = SessionLocal()
        try:
            barrier.wait(timeout=5)
            proj = db.get(Project, project_id)
            code = sequences.generate_unique_code(db, proj, ArtefactType.REQUIREMENT, "REQ")
            db.commit()
            with codes_lock:
                codes.append(code)
        except BaseException as exc:  # noqa: BLE001 - surfaced via `errors` for the assertion below
            errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, errors
    assert sorted(codes) == ["REQ-001", "REQ-002"]
