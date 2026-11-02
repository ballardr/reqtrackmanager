"""
Module: services.perf_dataset.build

Builds a whole dataset: the structure through the API, then every project's records through the registered
generators, then statistics and an integrity check.

Responsibilities:
- Run `skeleton.build_skeleton`, then for each project (parents first) call every registered
  `PerfDatasetGenerator` in `order`, committing after each project.
- Refresh planner statistics (`ANALYZE`) so a query plan measured later matches a database that has been in use,
  not a freshly bulk-loaded one.
- Check the result (`check_integrity`) and return a manifest the load generator and the results bundle use.

Design decisions:
- Refuses to run unless `PERF_STACK=1`: the generator writes thousands of rows with real-looking content, and
  must never run by accident in a container that holds real data. Only the perf stack's compose override sets it.
- The manifest carries ids, counts and the realised link-degree histogram, never credentials or personal data.

Dependencies: `perf_dataset.skeleton/spec/context/registry`, `modules.registry`, SQLAlchemy.
"""

from __future__ import annotations

import os
import random
import uuid
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.requirement import Requirement, RequirementVersion
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.modules.registry import get_perf_generators
from app.services.perf_dataset.context import PerfProjectContext
from app.services.perf_dataset.skeleton import Client, OrgPlan, Skeleton, build_skeleton
from app.services.perf_dataset.spec import DatasetSpec
from app.services.project_hierarchy import resolve_effective_action_types

GUARD_ENV = "PERF_STACK"
#: Requirement ids per project kept in the manifest for the load generator to address.
SAMPLE_SIZE = 200


def schema_head() -> str:
    """The migration head of the code in this image (core and module directories), without touching the database.

    Used in a snapshot's key, so a snapshot made on an older schema is never reused as if it were current.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from app.migrations import _BACKEND_DIR
    from app.modules.registry import configure_alembic_version_locations

    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    configure_alembic_version_locations(cfg)
    return ",".join(sorted(ScriptDirectory.from_config(cfg).get_heads()))


class RefusedToRun(RuntimeError):
    """The environment is not the throwaway performance stack."""


def require_perf_stack() -> None:
    """Raises `RefusedToRun` unless this process runs inside the performance stack (`PERF_STACK=1`)."""
    if os.environ.get(GUARD_ENV) != "1":
        raise RefusedToRun(
            f"{GUARD_ENV}=1 is not set: this container is not the performance stack, and the dataset generator "
            "writes large volumes of data. It is set only by perf/docker-compose.perf.yml."
        )


def _requirement_link_types(db: Session, org: OrgPlan) -> list[tuple[uuid.UUID, str]]:
    """`(id, nesting_scope)` of the organisation's link types that may join two requirements."""
    rows = db.scalars(
        select(RequirementLinkTypeDefinition)
        .where(
            RequirementLinkTypeDefinition.organization_id == uuid.UUID(org.id),
            RequirementLinkTypeDefinition.project_id.is_(None),
            RequirementLinkTypeDefinition.dedicated_endpoint.is_(False),
        )
        .order_by(RequirementLinkTypeDefinition.sort_order)
    ).all()
    usable = []
    for row in rows:
        if row.allowed_source_types and "requirement" not in row.allowed_source_types:
            continue
        if row.allowed_target_types and "requirement" not in row.allowed_target_types:
            continue
        usable.append((row.id, getattr(row.nesting_scope, "value", str(row.nesting_scope))))
    return usable


def _record_types() -> dict[str, dict[str, Any]]:
    """What the load generator needs to address each record type through the API, from the registry: its project list
    path (relative to `/api/v1/projects/{id}/`), whether it has a detail and comments, and whether its list imports
    (export is offered for every type). Taken from the scaling probes, so a module that registers one is covered
    with no edit here."""
    from app.modules.registry import get_not_importable_types, get_scaling_probes

    not_importable = get_not_importable_types()
    return {
        artefact_type: {
            "list_path": probe.list_path, "has_detail": probe.has_detail, "has_comments": probe.has_comments,
            "importable": artefact_type not in not_importable,
        }
        for artefact_type, probe in sorted(get_scaling_probes().items())
    }


def _bucket_add(total: dict[str, int], part: dict[str, int]) -> None:
    """Adds one project's link-degree histogram into the dataset total (`max` and `*_max` take the maximum)."""
    for key, value in part.items():
        total[key] = max(total.get(key, 0), value) if key == "max" or key.endswith("_max") else total.get(key, 0) + value


def check_integrity(db: Session, project_ids: list[uuid.UUID]) -> list[str]:
    """Checks what the application relies on in generated data.

    Args:
        db: A session.
        project_ids: The generated projects.

    Returns:
        Problems found, empty when the data is consistent. Checked: each requirement has exactly one current
        version and contiguous version numbers, each project's counters are past its highest generated code, and
        every requirement link end resolves to a requirement.
    """
    problems: list[str] = []
    if not project_ids:
        return ["no projects were generated"]
    no_current = db.scalar(
        select(func.count())
        .select_from(Requirement)
        .where(
            Requirement.project_id.in_(project_ids),
            ~select(RequirementVersion.id).where(RequirementVersion.requirement_id == Requirement.id, RequirementVersion.valid_to.is_(None)).exists(),
        )
    )
    if no_current:
        problems.append(f"{no_current} requirements have no current version")
    gaps = db.execute(
        text(
            "SELECT count(*) FROM (SELECT requirement_id FROM requirement_versions v JOIN requirements r ON r.id = v.requirement_id "
            "WHERE r.project_id = ANY(:ids) GROUP BY requirement_id HAVING max(version_number) <> count(*) "
            "OR count(*) FILTER (WHERE valid_to IS NULL) <> 1) x"
        ),
        {"ids": project_ids},
    ).scalar()
    if gaps:
        problems.append(f"{gaps} requirements have non-contiguous versions or more than one current version")
    for project in db.scalars(select(Project).where(Project.id.in_(project_ids))):
        highest = db.scalar(select(func.count()).select_from(Requirement).where(Requirement.project_id == project.id)) or 0
        if project.next_requirement_seq <= highest:
            problems.append(f"project {project.id}: next_requirement_seq {project.next_requirement_seq} is not past {highest} requirements")
    dangling = db.execute(
        text(
            "SELECT count(*) FROM artefact_links l WHERE l.source_type = 'requirement' AND l.target_type = 'requirement' "
            "AND (l.source_id = ANY(SELECT id FROM requirements WHERE project_id = ANY(:ids))) "
            "AND (NOT EXISTS (SELECT 1 FROM requirements t WHERE t.id = l.target_id))"
        ),
        {"ids": project_ids},
    ).scalar()
    if dangling:
        problems.append(f"{dangling} requirement links point at a requirement that does not exist")
    return problems


#: Shared ids that are not records of the project's own numbered types (they have no sequence counter).
_UNNUMBERED_SHARED = frozenset({"requirement_approved", "hubs", "compliance_requirement", "project_compliance_requirement",
                                "compliance_required_action_assessment"})


def _counter_problems(db: Session, ctx: PerfProjectContext) -> list[str]:
    """Checks the project's sequence counters against what was generated: one `ProjectSequenceCounter` row per
    numbered type, `next_seq` one past the number of records written (so the next record a person creates is
    numbered correctly, and a code is never reused)."""
    from sqlalchemy import select

    from app.models.sequence import ProjectSequenceCounter

    counters = {
        c.artefact_type: c.next_seq
        for c in db.scalars(select(ProjectSequenceCounter).where(ProjectSequenceCounter.project_id == ctx.project_uuid))
    }
    problems = []
    for artefact_type, ids in ctx.shared.items():
        if artefact_type in _UNNUMBERED_SHARED or artefact_type in ("requirement", "requirement_action") or not ids:
            continue
        if counters.get(artefact_type) != len(ids) + 1:
            problems.append(f"project {ctx.project.id}: {artefact_type} counter is {counters.get(artefact_type)}, expected {len(ids) + 1}")
    return problems


def generate_dataset(
    db: Session,
    client: Client,
    spec: DatasetSpec,
    *,
    admin_email: str,
    admin_password: str,
    user_password: str,
    say: Any = print,
    enforce_guard: bool = True,
) -> dict:
    """Generates the dataset the spec describes and returns its manifest.

    Args:
        db: A session on the application's database (committed per project).
        client: An httpx-compatible client for the running application (the structure is created through it).
        spec: What to generate.
        admin_email / admin_password: The server administrator.
        user_password: The password every generated person gets.
        say: Progress sink.
        enforce_guard: False only in the backend tests, which run against their own throwaway database.

    Returns:
        The manifest: the spec, row counts by table, the realised link-degree histogram, integrity problems and the
        organisations and projects (ids and logins only, no secrets).

    Raises:
        RefusedToRun: If `PERF_STACK=1` is not set and `enforce_guard` is true.
        SkeletonError: If the structure cannot be created.
    """
    if enforce_guard:
        require_perf_stack()
    skeleton: Skeleton = build_skeleton(
        client,
        spec,
        admin_email=admin_email,
        admin_password=admin_password,
        user_password=user_password,
        say=say,
    )
    generators = sorted(get_perf_generators().items(), key=lambda item: item[1].order)
    record_types = _record_types()
    counts: dict[str, int] = {}
    histogram: dict[str, int] = {}
    project_ids: list[uuid.UUID] = []
    counter_problems: list[str] = []
    link_pairs: dict[str, dict[str, int]] = {}
    project_entries = []
    position = 0
    for org in skeleton.organisations:
        link_types = _requirement_link_types(db, org)
        user_ids = [uuid.UUID(u) for u in org.user_ids]
        shared_by_project: dict[str, dict[str, list[uuid.UUID]]] = {}
        org_state: dict[str, Any] = {}
        children_by_parent: dict[str, list[str]] = {}
        for project in org.projects:
            position += 1
            ctx = PerfProjectContext(
                db=db,
                spec=spec,
                org=org,
                project=project,
                rng=random.Random(f"{spec.seed}:{position}"),
                user_ids=user_ids,
                link_type_ids=link_types,
                action_type_ids=[t.id for t in resolve_effective_action_types(db, uuid.UUID(project.id))],
                parent_shared=shared_by_project.get(project.parent_id) if project.parent_id else None,
                org_state=org_state,
                siblings=[
                    (uuid.UUID(pid), shared_by_project[pid]) for pid in children_by_parent.get(project.parent_id or "", [])
                ] if project.parent_id else [],
                say=say,
            )
            for _artefact_type, generator in generators:
                generator.generate(ctx)
            db.commit()
            counter_problems.extend(_counter_problems(db, ctx))
            shared_by_project[project.id] = ctx.shared
            if project.parent_id:
                children_by_parent.setdefault(project.parent_id, []).append(project.id)
            for pair, stats in ctx.pair_stats.items():
                total = link_pairs.setdefault(pair, {"links": 0, "max_partner_degree": 0})
                total["links"] += stats["links"]
                total["max_partner_degree"] = max(total["max_partner_degree"], stats["max_partner_degree"])
            project_ids.append(uuid.UUID(project.id))
            for table, written in ctx.counts.items():
                counts[table] = counts.get(table, 0) + written
            _bucket_add(histogram, ctx.histogram)
            requirement_ids = ctx.shared.get("requirement", [])
            stride = max(1, len(requirement_ids) // SAMPLE_SIZE)
            project_entries.append(
                {
                    "id": project.id,
                    "organization_id": org.id,
                    "parent_id": project.parent_id,
                    "depth": project.depth,
                    "requirements": len(requirement_ids),
                    # What the load generator needs to address records without listing the project first.
                    "component_id": project.components[0][0],
                    "category_id": project.categories[0][0],
                    "stage_id": project.stage_ids[0] if project.stage_ids else None,
                    "action_type_id": str(ctx.action_type_ids[0]) if ctx.action_type_ids else None,
                    "requirement_sample": [str(i) for i in requirement_ids[::stride][:SAMPLE_SIZE]],
                    "hubs": [str(i) for i in ctx.shared.get("hubs", [])],
                    # Sampled ids of every record type the scenarios address by type (`record_types`).
                    "type_samples": {
                        t: [str(i) for i in ids[:: max(1, len(ids) // SAMPLE_SIZE)][:SAMPLE_SIZE]]
                        for t, ids in ctx.shared.items() if t in record_types and ids
                    },
                    # The three most-linked records of every type with links, for the scenarios to address a hub.
                    "type_hubs": {
                        artefact_type: [str(i) for i, _d in sorted(counts.items(), key=lambda item: -item[1])[:3]]
                        for artefact_type, counts in ctx.degrees.items() if counts
                    },
                }
            )
            if position % 10 == 0 or position == spec.total_projects:
                say(f"generated {position}/{spec.total_projects} projects")
    say("analyzing tables")
    db.execute(text("ANALYZE"))
    db.commit()
    problems = check_integrity(db, project_ids) + counter_problems
    return {
        "spec": spec.describe(),
        "rows": counts,
        "link_degree_histogram": histogram,
        "link_pairs": link_pairs,
        "record_types": record_types,
        "integrity_problems": problems,
        "link_rows_total": db.scalar(select(func.count()).select_from(ArtefactLink)),
        "organisations": [
            {
                "id": o.id, "index": o.index, "admin_email": o.admin_email, "member_emails": o.member_emails,
                "restricted_email": o.restricted_email, "user_ids": o.user_ids,
            }
            for o in skeleton.organisations
        ],
        "projects": project_entries,
    }
