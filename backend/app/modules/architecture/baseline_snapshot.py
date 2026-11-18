"""
Module: modules.architecture.baseline_snapshot

What the Architecture module puts in a baseline (`services.baseline`): one item per element, connection, diagram and
state machine diagram of the project, each a self-contained JSON copy of the record as it stands.

Responsibilities:
- `build`: the project's records as `{artefact type: [SnapshotEntry]}`, the one read the four providers and the compare
  routes share.
- `SNAPSHOT_PROVIDERS`: the four `BaselineSnapshotProvider`s registered on the module definition.

Design decisions (all Decided by: Agent):
- **One reader.** A record's snapshot is its project bundle entry (`export.export_project_data`), so ports, tags, places,
  boxes, notes, anchors, toggles, states and transitions travel with the same portable keys as a bundle and the snapshot
  cannot drift from the export. A state machine diagram carries its states and transitions inside it (a state is not a
  baseline item of its own).
- **No personal data, no discussion.** Entries go through `interchange.scrub` (comments and their pins, `*_email` keys,
  an element's owner), and the creation and archive instants are dropped: a baseline outlives its records, travels in the
  project bundle and is read by every member who may see the architecture. Archived records are not captured.
- **A reference never reaches past the project.** An element another owner shares is written as its owner and code only,
  and only when the *project* may read it (`Viewer.of_project`, a subset of any member's view); otherwise the reference is
  emptied, so a snapshot never discloses what the project itself cannot see, whoever took it.
- **Whole project only.** The records belong to no component, so a component's own stage baseline captures none.
- **Computed once per baseline.** The four providers share one read, kept on the session for the context object that
  triggered it (`db.info`), so a baseline costs one bundle export, not four.

Dependencies: `export`, `interchange`, `visibility`, this module's models and `modules.registry`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.modules.architecture import export as bundle
from app.modules.architecture import interchange
from app.modules.architecture._shared import (
    CONNECTION_MANAGE_PERMISSION,
    DIAGRAM_MANAGE_PERMISSION,
    ELEMENT_MANAGE_PERMISSION,
    STATE_MACHINE_MANAGE_PERMISSION,
)
from app.modules.architecture.models import (
    ArchitectureConnection,
    ArchitectureDiagram,
    ArchitectureElement,
    ArchitectureStateMachineDiagram,
)
from app.modules.architecture.service import (
    CONNECTION_ARTEFACT_TYPE,
    DIAGRAM_ARTEFACT_TYPE,
    ELEMENT_ARTEFACT_TYPE,
    STATE_MACHINE_ARTEFACT_TYPE,
)
from app.modules.architecture.visibility import Viewer
from app.modules.registry import BaselineSnapshotContext, BaselineSnapshotProvider, BaselineSnapshotRecord

#: Bundle section and record table of each type a baseline holds, in the order they are listed.
_SECTIONS: dict[str, tuple[str, Any]] = {
    ELEMENT_ARTEFACT_TYPE: (bundle.ELEMENTS_KEY, ArchitectureElement),
    CONNECTION_ARTEFACT_TYPE: (bundle.CONNECTIONS_KEY, ArchitectureConnection),
    DIAGRAM_ARTEFACT_TYPE: (bundle.DIAGRAMS_KEY, ArchitectureDiagram),
    STATE_MACHINE_ARTEFACT_TYPE: (bundle.STATE_MACHINES_KEY, ArchitectureStateMachineDiagram),
}
#: Keys of a bundle entry a snapshot leaves out besides what `interchange.scrub` removes (instants of no meaning to a baseline).
_DROPPED = frozenset({"created_at", "is_archived", "archived_at"})
_CACHE_KEY = "architecture_baseline_snapshot"


@dataclass(frozen=True)
class SnapshotEntry:
    """One record as a baseline holds it.

    Attributes:
        item_id: The live record's id.
        content: The scrubbed bundle entry (`unique_code`, `name`, the record's fields, its ports, boxes, states ...).
    """

    item_id: UUID
    content: dict[str, Any]


def build(db: Session, project: Project) -> dict[str, list[SnapshotEntry]]:
    """The project's non-archived records as a baseline would hold them.

    Args:
        db: Active session (read only).
        project: The project.

    Returns:
        `{artefact type: entries}`, each list ordered by code, with every type present (possibly empty).
    """
    exported, _assets = bundle.export_project_data(db, project)
    data = interchange.scrub({key: exported.get(key, []) for key, _model in _SECTIONS.values()})
    data = interchange.empty_hidden_refs(db, Viewer.of_project(project.id, project.organization_id), project, data)
    result: dict[str, list[SnapshotEntry]] = {}
    for artefact_type, (key, model) in _SECTIONS.items():
        ids = {code: record_id for record_id, code in db.execute(select(model.id, model.unique_code).where(model.project_id == project.id))}
        result[artefact_type] = [
            SnapshotEntry(item_id=ids[entry["unique_code"]], content={k: v for k, v in entry.items() if k not in _DROPPED})
            for entry in data.get(key, [])
            if not entry.get("is_archived") and entry.get("unique_code") in ids
        ]
    return result


def _snapshot_of(artefact_type: str):
    """The provider function for one type: it reads (or reuses) the whole-project snapshot and returns its share."""

    def snapshot(db: Session, project: Project, context: BaselineSnapshotContext) -> list[BaselineSnapshotRecord]:
        if context.component_id is not None:
            return []
        cached = db.info.get(_CACHE_KEY)
        if cached is None or cached[0] is not context or cached[1] != project.id:
            cached = (context, project.id, build(db, project))
            db.info[_CACHE_KEY] = cached
        return [BaselineSnapshotRecord(item_id=e.item_id, content=e.content) for e in cached[2][artefact_type]]

    return snapshot


SNAPSHOT_PROVIDERS: dict[str, BaselineSnapshotProvider] = {
    ELEMENT_ARTEFACT_TYPE: BaselineSnapshotProvider(snapshot=_snapshot_of(ELEMENT_ARTEFACT_TYPE), permission=ELEMENT_MANAGE_PERMISSION),
    CONNECTION_ARTEFACT_TYPE: BaselineSnapshotProvider(
        snapshot=_snapshot_of(CONNECTION_ARTEFACT_TYPE), permission=CONNECTION_MANAGE_PERMISSION,
    ),
    DIAGRAM_ARTEFACT_TYPE: BaselineSnapshotProvider(snapshot=_snapshot_of(DIAGRAM_ARTEFACT_TYPE), permission=DIAGRAM_MANAGE_PERMISSION),
    STATE_MACHINE_ARTEFACT_TYPE: BaselineSnapshotProvider(
        snapshot=_snapshot_of(STATE_MACHINE_ARTEFACT_TYPE), permission=STATE_MACHINE_MANAGE_PERMISSION,
    ),
}
