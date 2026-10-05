"""
Module: modules.stakeholders.relationship_export

The §10.5 relationships part of this module's project bundle export/import
(Phase 3); `module.py` composes it with the Persona, Stakeholder and Need halves.

Design decisions:
- Only a holder's relationships to records *of this project* travel, so a
  shared org-level Stakeholder/Persona exports just this project's links.
- Cross-references use portable keys, never database ids: the holder is its
  name and scope, a Requirement is its unique code, and any other target (Pain
  Point, Decision — which this module cannot import) is the label its owning
  module's summary provider gives it. A label that matches no record, or more
  than one, is skipped with a warning rather than guessed at or failing the import.
- Runs last among this module's import steps: Stakeholders and Personas must
  exist, and the core import creates Requirements, then other modules' hooks
  (registered before this one) recreate Pain Points and Decisions.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.requirement import Requirement
from app.models.user import User
from app.modules.stakeholders import relationships as rel
from app.modules.stakeholders.enums import PersonaScope, StakeholderScope
from app.modules.stakeholders.models import Persona, Stakeholder
from app.modules.stakeholders.service import (
    PERSONA_ARTEFACT_TYPE,
    STAKEHOLDER_ARTEFACT_TYPE,
    get_current_persona_version,
    get_current_stakeholder_version,
)
from app.services.bundle_common import BundleImportWarnings, UserResolver

_KEY = "project_stakeholder_relationships"


def _visible_holders(db: Session, project: Project) -> list[tuple[str, Stakeholder | Persona, str]]:
    """`(kind, record, name)` for every Stakeholder/Persona the project can see."""
    out: list[tuple[str, Stakeholder | Persona, str]] = []
    for s in db.scalars(select(Stakeholder).where(
        ((Stakeholder.organization_id == project.organization_id) & (Stakeholder.scope == StakeholderScope.ORGANIZATION))
        | ((Stakeholder.project_id == project.id) & (Stakeholder.scope == StakeholderScope.PROJECT))
    )):
        out.append((STAKEHOLDER_ARTEFACT_TYPE, s, get_current_stakeholder_version(db, s.id).name))
    for p in db.scalars(select(Persona).where(
        ((Persona.organization_id == project.organization_id) & (Persona.scope == PersonaScope.ORGANIZATION))
        | ((Persona.project_id == project.id) & (Persona.scope == PersonaScope.PROJECT))
    )):
        out.append((PERSONA_ARTEFACT_TYPE, p, get_current_persona_version(db, p.id).name))
    return out


def export_project_data(db: Session, project: Project) -> dict[str, Any]:
    """The project's stakeholder/persona relationships to its own records."""
    out = []
    for kind, record, name in _visible_holders(db, project):
        for link, relationship, summary in rel.list_relationships(db, project, kind, record.id):
            link_target_type = link.target_type
            if link_target_type == rel.REQUIREMENT_TARGET:
                requirement = db.get(Requirement, summary.id)
                ref = requirement.unique_code if requirement is not None else None
            else:
                ref = summary.label
            if ref is None:
                continue
            out.append({
                "holder": {"kind": kind, "name": name, "scope": record.scope.value},
                "relationship": relationship.key, "target_type": link_target_type, "target_ref": ref,
            })
    return {_KEY: out}


def import_project_data(
    db: Session, project: Project, data: dict[str, Any], file_bytes_by_ref: dict[str, bytes], current_user: User,
    users: UserResolver, warnings: BundleImportWarnings,
) -> None:
    """Recreates the relationships, skipping (with a warning) any whose holder or
    target the destination project lacks, or whose target is ambiguous."""
    holders = {(kind, name, record.scope.value): record.id for kind, record, name in _visible_holders(db, project)}
    requirement_ids = {
        r.unique_code: r.id for r in db.scalars(select(Requirement).where(Requirement.project_id == project.id))
    }
    labels: dict[str, dict[str, list[Any]]] = {}
    for entry in data.get(_KEY, []):
        holder = entry["holder"]
        context = f"Relationship of {holder['name']!r}"
        holder_id = holders.get((holder["kind"], holder["name"], holder["scope"]))
        kind = rel.get_kind(entry["relationship"])
        if holder_id is None or kind is None:
            warnings.add(f"{context}: holder or relationship kind not found — skipped.")
            continue
        target_type = entry["target_type"]
        if target_type == rel.REQUIREMENT_TARGET:
            target = rel.resolve_target(db, project, target_type, requirement_ids[entry["target_ref"]]) \
                if entry["target_ref"] in requirement_ids else None
        else:
            if target_type not in labels:
                by_label: dict[str, list[Any]] = {}
                for s in rel.list_targets(db, project, target_type):
                    by_label.setdefault(s.label, []).append(s)
                labels[target_type] = by_label
            matches = labels[target_type].get(entry["target_ref"], [])
            target = matches[0] if len(matches) == 1 else None
        if target is None:
            warnings.add(f"{context}: {target_type} {entry['target_ref']!r} not found or ambiguous — skipped.")
            continue
        try:
            rel.add_relationship(
                db, holder["kind"], holder_id, kind, target, target_type, current_user,
                organization_id=project.organization_id,
            )
        except ValueError as exc:
            warnings.add(f"{context}: {exc}")
    db.flush()
