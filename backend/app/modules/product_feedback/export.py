"""
Module: modules.product_feedback.export

This module's contribution to the core org/project bundle export/import (`services.org_export` /
`project_export`), registered through `ModuleOrgBundleHooks` / `ModuleProjectBundleHooks` on `MODULE_DEFINITION`
rather than those core files importing this module.

- Org level: the organisation's inbox requests and the active merges between them.
- Project level: the project's submission policy and its requests (current content and status, tags,
  evidence attachments, their "Requested by" links and the active merge of a duplicate).

Design decisions (all Decided by: Agent):
- A request's scoring levels (one per axis) travel by *axis and name* and are matched to the target organisation's
  `enhancement_request` levels; one the target lacks is left unset with a warning, so the request is "not
  scored" on that axis rather than silently re-scored. The score is derived and never exported; scoring
  configuration (levels, bands) is not part of a bundle.
- A request travels as its *current* content and status only. Version history, comments and comment
  attachments are not carried: a bundle is a migration artefact, and the imported request starts at version 1
  attributed to the importer where the author cannot be matched.
- The `ENH-nnn` code is carried as information only; an import numbers its records afresh from the target's
  counter, so a restored project can never collide with a code it already uses.
- An owner is `{type, email | name}` (`services.principals`); one the target cannot match is left unset with a
  warning. Org-level files cannot travel (the org hook receives no bytes).
- Requesters and merges refer to other records by portable keys, never ids (`import_late_project_data`, run
  after every module's own import so the Stakeholders, Personas and Engagements exist): a requester is its
  type and title (`services.codes.label_title`; a code is renumbered on import), a merge names the canonical
  request by its exported code. Only active merges travel; ended ones are history, like versions. A requester
  that matches no record, or more than one, is skipped with a warning rather than guessed at.
- The org-level merge skips an inbox request whose title and description the organisation already holds, so a
  re-import is idempotent.

Dependencies: `services.bundle_common`, `services.principals`, `services.tags`, this module's models and service.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.organization import Organization
from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.models.user import User
from app.modules.product_feedback.demand import REQUESTED_BY_FORWARD, REQUESTED_BY_REVERSE, REQUESTER_TYPES
from app.modules.product_feedback.enums import EnhancementRequestScope, EnhancementRequestStatus, SubmissionPolicy
from app.modules.product_feedback.models import (
    EnhancementRequest,
    EnhancementRequestFile,
    EnhancementRequestMerge,
    EnhancementRequestVersion,
    EnhancementRequestVersionScore,
    ProjectFeedbackSettings,
)
from app.modules.product_feedback.scoring import REQUEST_SCORING_SCHEME, REQUEST_SCORING_SCHEME_KEY
from app.modules.product_feedback.service import (
    REQUEST_ARTEFACT_TYPE,
    REQUEST_CODE_PREFIX,
    RecordOwner,
    set_submission_policy,
    version_levels,
)
from app.modules.registry import ScoringSchemeDefinition, get_artefact_summaries_in_project
from app.services.bundle_common import BundleImportWarnings, UserResolver, export_file_links, import_bundled_file, prime_file_links
from app.services.codes import label_title
from app.services.link_types import ensure_org_link_type
from app.services.principals import principal_columns_from_bundle, principal_to_bundle
from app.services.relationships import create_link
from app.services.scoring import list_levels, seed_missing_scoring_levels
from app.services.scoring_custom import effective_scheme, export_definitions, import_definitions
from app.services.sequences import code_owner, generate_unique_code
from app.services.tags import prime_record_tag_names, record_tag_names, restore_record_tags

_PENDING_CODES = "product_feedback_imported_codes"


def _j(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _emails(db: Session, user_ids: set[UUID | None]) -> dict[UUID, str]:
    ids = {u for u in user_ids if u is not None}
    return {u.id: u.email for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


def _level_refs(db: Session, organization_id: UUID) -> dict[UUID, dict[str, str]]:
    """`{level id: {"axis", "name"}}` for the organisation's `enhancement_request` scoring levels."""
    return {
        level.id: {"axis": axis, "name": level.name}
        for axis, levels in list_levels(db, organization_id, REQUEST_SCORING_SCHEME_KEY).items() for level in levels
    }


def _level_ids(db: Session, organization_id: UUID) -> dict[tuple[str, str], UUID]:
    """`{(axis, level name): level id}` for the organisation's `enhancement_request` scoring levels, seeding any
    the organisation is still missing."""
    seed_missing_scoring_levels(db, organization_id)
    return {
        (axis, level.name): level.id
        for axis, levels in list_levels(db, organization_id, REQUEST_SCORING_SCHEME_KEY).items() for level in levels
    }


def _export_requests(
    db: Session, organization_id: UUID, pairs: list[tuple[EnhancementRequest, EnhancementRequestVersion]],
    assets: dict[UUID, FileAsset] | None,
) -> list[dict[str, Any]]:
    """The bundle rows of `(request, current version)` pairs; attachments only when `assets` is given."""
    ids = [r.id for r, _ in pairs]
    levels = _level_refs(db, organization_id)
    stored = version_levels(db, [v.id for _, v in pairs])
    prime_record_tag_names(db, REQUEST_ARTEFACT_TYPE, ids)
    if assets is not None:
        prime_file_links(db, EnhancementRequestFile, "request_id", ids)
    emails = _emails(db, {u for r, v in pairs for u in (r.creator_id, r.archived_by, v.created_by)})
    out = []
    for request, version in pairs:
        entry: dict[str, Any] = {
            "unique_code": request.unique_code, "title": version.title, "description": version.description,
            "status": version.status.value, "decline_reason": version.decline_reason,
            "external_ref_url": version.external_ref_url, "external_ref_key": version.external_ref_key,
            "owner": principal_to_bundle(db, version.owner_type, version.owner_id),
            "levels": {axis: levels[level_id] for axis, level_id in stored[version.id].items() if level_id in levels},
            "created_by_email": emails.get(request.creator_id), "created_at": _j(request.created_at),
            "is_archived": request.is_archived, "archived_at": _j(request.archived_at),
            "archived_by_email": emails.get(request.archived_by) if request.archived_by else None,
            "tags": record_tag_names(db, REQUEST_ARTEFACT_TYPE, request.id),
        }
        if assets is not None:
            entry["attachments"] = export_file_links(db, EnhancementRequestFile, "request_id", request.id, assets)
        out.append(entry)
    return out


def _import_scoring_definitions(
    db: Session, organization_id: UUID, project_id: UUID | None, data: dict[str, Any], warnings: BundleImportWarnings,
    current_user: User | None = None,
) -> dict[str, str]:
    """Recreates the bundle's custom scoring axes, models and hidden criteria for the tier before any request, so
    their levels exist when the requests are matched. Returns the exported-to-local axis key map."""
    definitions = data.get("scoring_definitions")
    if not definitions:
        return {}
    actor_id = current_user.id if current_user is not None else None  # an organisation import has no actor
    messages: list[str] = []
    mapping = import_definitions(
        db, organization_id, REQUEST_SCORING_SCHEME, project_id, definitions, actor_id, messages,
    )
    for message in messages:
        warnings.add(message)
    return mapping


def _imported_status(entry: dict[str, Any]) -> EnhancementRequestStatus:
    """The status to create an imported request with. A duplicate is created with the status it had before the
    merge and becomes a duplicate when `import_late_project_data` replays the merge, so a merge that cannot be
    replayed leaves an ordinary request, never a duplicate of nothing."""
    merged = entry.get("merged_into")
    return EnhancementRequestStatus(merged["prior_status"] if merged else entry.get("status", "new"))


def _import_request(
    db: Session, holder: RecordOwner, entry: dict[str, Any], users: UserResolver, warnings: BundleImportWarnings,
    current_user: User | None, file_bytes_by_ref: dict[str, bytes] | None, level_ids: dict[tuple[str, str], UUID],
    scheme: ScoringSchemeDefinition, axis_map: dict[str, str],
) -> EnhancementRequest:
    """Creates one request (numbered afresh) with its version 1, scoring levels, tags and attachments; a level
    `level_ids` (`_level_ids`) cannot match is left unset with a warning. `axis_map` re-points an exported custom
    axis key at the key it was given in this organisation."""
    context = entry.get("unique_code", "request")
    creator_id = users.resolve(entry.get("created_by_email"), required=True, context=f"Request {context} creator")
    archived = bool(entry.get("is_archived"))
    archiver_id = users.resolve(entry.get("archived_by_email"), required=False, context=f"Request {context} archiver")
    owner = code_owner(
        db, is_org_scope=not holder.is_project, organization_id=holder.organization_id, project_id=holder.project_id,
    )
    request = EnhancementRequest(
        scope=holder.scope, organization_id=None if holder.is_project else holder.organization_id,
        project_id=holder.project_id, creator_id=creator_id, is_archived=archived,
        archived_at=_dt(entry.get("archived_at")), archived_by=(archiver_id or creator_id) if archived else None,
        unique_code=generate_unique_code(db, owner, REQUEST_ARTEFACT_TYPE, REQUEST_CODE_PREFIX),
    )
    db.add(request)
    db.flush()
    now = datetime.now(UTC)
    levels: dict[str, UUID] = {}
    for exported_key, ref in (entry.get("levels") or {}).items():
        axis_key = axis_map.get(exported_key, exported_key)
        if scheme.axis(axis_key) is None or not ref:
            continue
        found = level_ids.get((axis_map.get(ref["axis"], ref["axis"]), ref["name"]))
        if found is None or axis_map.get(ref["axis"], ref["axis"]) != axis_key:
            warnings.add(f"Request {context}: scoring level {ref['name']!r} ({ref['axis']}) not found — left unset.")
        else:
            levels[axis_key] = found
    version = EnhancementRequestVersion(
        request_id=request.id, version_number=1, valid_from=now, valid_to=None, title=entry["title"],
        description=entry.get("description", ""), status=_imported_status(entry),
        external_ref_url=entry.get("external_ref_url"), external_ref_key=entry.get("external_ref_key"),
        decline_reason=entry.get("decline_reason", ""),
        **principal_columns_from_bundle(
            db, entry, "owner", organization_id=holder.organization_id, project_id=holder.project_id, users=users,
            warnings=warnings, context=f"Request {context} owner", required=False,
        ),
        change_note="Imported from bundle.", created_by=creator_id, created_at=now,
    )
    db.add(version)
    db.flush()
    for axis_key, level_id in levels.items():
        db.add(EnhancementRequestVersionScore(version_id=version.id, axis_key=axis_key, level_id=level_id))
    db.flush()
    restore_record_tags(
        db, organization_id=holder.organization_id, record_project_id=holder.project_id, actor_id=creator_id,
        artefact_type=REQUEST_ARTEFACT_TYPE, artefact_id=request.id, names=entry.get("tags"),
    )
    for attachment in entry.get("attachments", []):
        data = (file_bytes_by_ref or {}).get(attachment["file_ref"])
        if data is None:
            continue
        uploader_id = users.resolve(
            attachment.get("linked_by_email"), required=False, context="Request attachment uploader",
        ) or (current_user.id if current_user is not None else None)
        if uploader_id is None:
            continue
        asset = import_bundled_file(
            db, organization_id=holder.organization_id, uploaded_by=uploader_id, filename=attachment["filename"],
            content_type=attachment.get("content_type") or "application/octet-stream", data=data,
            confidential=bool(attachment.get("confidential")),
        )
        db.add(EnhancementRequestFile(request_id=request.id, file_id=asset.id, linked_by=uploader_id, created_at=now))
    return request


# --- Org level ---------------------------------------------------------------


def export_org_data(db: Session, org: Organization) -> dict[str, Any]:
    """`ModuleOrgBundleHooks.export`: the organisation's inbox requests (archived included: a bundle is a backup)."""
    pairs = db.execute(
        select(EnhancementRequest, EnhancementRequestVersion)
        .join(EnhancementRequestVersion, EnhancementRequestVersion.request_id == EnhancementRequest.id)
        .where(
            EnhancementRequest.organization_id == org.id,
            EnhancementRequest.scope == EnhancementRequestScope.ORGANIZATION,
            EnhancementRequestVersion.valid_to.is_(None),
        ).order_by(EnhancementRequest.unique_code)
    ).all()
    entries = _export_requests(db, org.id, [tuple(p) for p in pairs], None)
    _add_merges(db, [r for r, _ in pairs], entries)
    return {"enhancement_requests": entries, "scoring_definitions": export_definitions(db, org.id, REQUEST_SCORING_SCHEME, None)}


def import_org_data(
    db: Session, org: Organization, data: dict[str, Any], users: UserResolver, warnings: BundleImportWarnings,
    resolutions: dict[str, str] | None,
) -> None:
    """`ModuleOrgBundleHooks.import_`: recreates the inbox requests, skipping one the organisation already holds."""
    existing = {
        (v.title, v.description)
        for v in db.scalars(
            select(EnhancementRequestVersion).join(EnhancementRequest, EnhancementRequest.id == EnhancementRequestVersion.request_id)
            .where(
                EnhancementRequest.organization_id == org.id, EnhancementRequestVersion.valid_to.is_(None),
            )
        )
    }
    imported: dict[str, UUID] = {}
    entries = data.get("enhancement_requests", [])
    axis_map = _import_scoring_definitions(db, org.id, None, data, warnings)
    level_ids = _level_ids(db, org.id) if entries else {}
    scheme = effective_scheme(db, org.id, REQUEST_SCORING_SCHEME, None)
    for entry in entries:
        key = (entry["title"], entry.get("description", ""))
        if key in existing:
            warnings.add(f"Inbox request {entry['title']!r} skipped — the organisation already has one like it.")
            continue
        existing.add(key)
        request = _import_request(db, RecordOwner(org.id), entry, users, warnings, None, None, level_ids, scheme, axis_map)
        if entry.get("unique_code"):
            imported[entry["unique_code"]] = request.id
    _replay_merges(db, entries, imported, users, warnings, None)
    db.flush()


# --- Project level -----------------------------------------------------------


def export_project_data(db: Session, project: Project) -> tuple[dict[str, Any], dict[UUID, FileAsset]]:
    """`ModuleProjectBundleHooks.export`: the project's settings and requests with attachments (archived included)."""
    assets: dict[UUID, FileAsset] = {}
    pairs = db.execute(
        select(EnhancementRequest, EnhancementRequestVersion)
        .join(EnhancementRequestVersion, EnhancementRequestVersion.request_id == EnhancementRequest.id)
        .where(EnhancementRequest.project_id == project.id, EnhancementRequestVersion.valid_to.is_(None))
        .order_by(EnhancementRequest.unique_code)
    ).all()
    settings = db.scalar(select(ProjectFeedbackSettings).where(ProjectFeedbackSettings.project_id == project.id))
    entries = _export_requests(db, project.organization_id, [tuple(p) for p in pairs], assets)
    _add_requesters_and_merges(db, project, [r for r, _ in pairs], entries)
    return {
        "feedback_settings": {"submission_policy": settings.submission_policy.value} if settings else None,
        "enhancement_requests": entries,
        "scoring_definitions": export_definitions(db, project.organization_id, REQUEST_SCORING_SCHEME, project.id),
    }, assets


def _add_requesters_and_merges(
    db: Session, project: Project, requests: list[EnhancementRequest], entries: list[dict[str, Any]],
) -> None:
    """Adds `requested_by` (type and title of each visible requester record) and `merged_into` (the canonical
    request's exported code, for an active merge) to the exported `entries`, which are in `requests` order."""
    ids = [r.id for r in requests]
    wanted: dict[str, set[UUID]] = {}
    by_request: dict[UUID, list[tuple[str, UUID]]] = {}
    for source_id, target_type, target_id in db.execute(
        select(ArtefactLink.source_id, ArtefactLink.target_type, ArtefactLink.target_id)
        .join(RequirementLinkTypeDefinition, RequirementLinkTypeDefinition.id == ArtefactLink.link_type_id)
        .where(
            ArtefactLink.source_type == REQUEST_ARTEFACT_TYPE, ArtefactLink.source_id.in_(ids),
            ArtefactLink.target_type.in_(REQUESTER_TYPES), ArtefactLink.source_project_id.is_(None),
            RequirementLinkTypeDefinition.forward_name == REQUESTED_BY_FORWARD,
            RequirementLinkTypeDefinition.organization_id == project.organization_id,
        )
    ).all() if ids else []:
        by_request.setdefault(source_id, []).append((target_type, target_id))
        wanted.setdefault(target_type, set()).add(target_id)
    titles: dict[tuple[str, UUID], str] = {}
    for target_type, target_ids in wanted.items():
        found = get_artefact_summaries_in_project(db, project.id, target_type, sorted(target_ids, key=str)) or {}
        titles.update({(target_type, i): label_title(summary.label) for i, summary in found.items()})
    for request, entry in zip(requests, entries, strict=True):
        entry["requested_by"] = sorted(
            (
                {"type": target_type, "title": titles[(target_type, target_id)]}
                for target_type, target_id in by_request.get(request.id, ())
                if (target_type, target_id) in titles
            ),
            key=lambda e: (e["type"], e["title"]),
        )
    _add_merges(db, requests, entries)


def _add_merges(db: Session, requests: list[EnhancementRequest], entries: list[dict[str, Any]]) -> None:
    """Adds `merged_into` to each exported entry: for a duplicate with an active merge, the canonical request's
    exported code, its previous status and who merged it (else null). `entries` are in `requests` order."""
    ids = [r.id for r in requests]
    codes = {r.id: r.unique_code for r in requests}
    merges = {
        m.duplicate_id: m for m in db.scalars(select(EnhancementRequestMerge).where(
            EnhancementRequestMerge.duplicate_id.in_(ids), EnhancementRequestMerge.unmerged_at.is_(None),
        ))
    } if ids else {}
    emails = _emails(db, {m.merged_by for m in merges.values()})
    for request, entry in zip(requests, entries, strict=True):
        merge = merges.get(request.id)
        canonical_code = codes.get(merge.canonical_id) if merge is not None else None
        entry["merged_into"] = (
            {
                "canonical_code": canonical_code, "prior_status": merge.prior_status.value,
                "merged_by_email": emails.get(merge.merged_by), "merged_at": _j(merge.merged_at),
            }
            if merge is not None and canonical_code is not None else None
        )


def import_project_data(
    db: Session, project: Project, data: dict[str, Any], file_bytes_by_ref: dict[str, bytes], current_user: User,
    users: UserResolver, warnings: BundleImportWarnings,
) -> None:
    """`ModuleProjectBundleHooks.import_`: recreates the project's settings and requests (numbered afresh)."""
    settings = data.get("feedback_settings")
    if settings:
        set_submission_policy(db, project.id, SubmissionPolicy(settings["submission_policy"]))
    holder = RecordOwner.of_project(project)
    imported: dict[str, UUID] = {}
    requests = data.get("enhancement_requests", [])
    axis_map = _import_scoring_definitions(db, project.organization_id, project.id, data, warnings, current_user)
    level_ids = _level_ids(db, project.organization_id) if requests else {}
    scheme = effective_scheme(db, project.organization_id, REQUEST_SCORING_SCHEME, project.id)
    for entry in requests:
        request = _import_request(
            db, holder, entry, users, warnings, current_user, file_bytes_by_ref, level_ids, scheme, axis_map,
        )
        if entry.get("unique_code"):
            imported[entry["unique_code"]] = request.id
    db.info[(_PENDING_CODES, project.id)] = imported
    db.flush()


def import_late_project_data(
    db: Session, project: Project, data: dict[str, Any], file_bytes_by_ref: dict[str, bytes], current_user: User,
    users: UserResolver, warnings: BundleImportWarnings,
) -> None:
    """`ModuleProjectBundleHooks.import_late`: recreates each request's "Requested by" links and active merge once
    the Stakeholders, Personas and Engagements of every module exist. A requester that matches no record, or more
    than one, is skipped with a warning; a merge the rules refuse is skipped with the reason."""
    imported: dict[str, UUID] = db.info.pop((_PENDING_CODES, project.id), {})
    entries = data.get("enhancement_requests", [])
    summaries: dict[str, dict[str, list[UUID]]] = {}
    link_type = None
    for entry in entries:
        request_id = imported.get(entry.get("unique_code", ""))
        if request_id is None:
            continue
        for requester in entry.get("requested_by", []):
            target_type = requester["type"]
            if target_type not in REQUESTER_TYPES:
                continue
            if target_type not in summaries:
                by_title: dict[str, list[UUID]] = {}
                for summary in (get_artefact_summaries_in_project(db, project.id, target_type, _all_ids(db, project, target_type)) or {}).values():
                    by_title.setdefault(label_title(summary.label), []).append(summary.id)
                summaries[target_type] = by_title
            matches = summaries[target_type].get(requester["title"], [])
            if len(matches) != 1:
                warnings.add(
                    f"Request {entry['unique_code']}: requester {requester['title']!r} ({target_type}) not found or "
                    "ambiguous — skipped."
                )
                continue
            if link_type is None:
                link_type = ensure_org_link_type(db, project.organization_id, REQUESTED_BY_FORWARD, REQUESTED_BY_REVERSE)
            try:
                with db.begin_nested():
                    create_link(
                        db, source_type=REQUEST_ARTEFACT_TYPE, source_id=request_id, target_type=target_type,
                        target_id=matches[0], link_type_id=link_type.id, created_by=current_user.id,
                        project_id=project.id, enforce_rules=False,
                    )
            except IntegrityError:
                continue
    _replay_merges(db, entries, imported, users, warnings, current_user)
    db.flush()


def _replay_merges(
    db: Session, entries: list[dict[str, Any]], imported: dict[str, UUID], users: UserResolver,
    warnings: BundleImportWarnings, current_user: User | None,
) -> None:
    """Recreates each entry's active merge between the requests just imported (`imported` maps an exported code
    to the new request id); a merge the rules refuse, or whose target did not travel, is skipped with a warning."""
    from app.modules.product_feedback.merge import merge_requests

    for entry in entries:
        merged = entry.get("merged_into")
        duplicate_id = imported.get(entry.get("unique_code", ""))
        canonical_id = imported.get((merged or {}).get("canonical_code", ""))
        if not merged or duplicate_id is None or canonical_id is None:
            if merged:
                warnings.add(f"Request {entry.get('unique_code')}: its merge target is not in the bundle — skipped.")
            continue
        duplicate, canonical = db.get(EnhancementRequest, duplicate_id), db.get(EnhancementRequest, canonical_id)
        if duplicate is None or canonical is None:
            continue
        merger = users.resolve(merged.get("merged_by_email"), required=False, context="Request merge author")
        actor = (db.get(User, merger) if merger else None) or current_user or db.get(User, duplicate.creator_id)
        if actor is None:
            continue
        try:
            with db.begin_nested():
                merge_requests(db, canonical, duplicate, actor)
        except ValueError as exc:
            warnings.add(f"Request {entry.get('unique_code')}: merge skipped — {exc}")
            continue
    db.flush()


def _all_ids(db: Session, project: Project, target_type: str) -> list[UUID]:
    """Every record id of `target_type` the project could see, for resolving a title to a record."""
    from app.modules.registry import list_artefact_summaries

    return [s.id for s in list_artefact_summaries(db, project.id, target_type)]
