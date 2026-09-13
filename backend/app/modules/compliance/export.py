"""
Module: modules.compliance.export

This module's contribution to the core org/project bundle export/import
system (`app.services.org_export`/`app.services.project_export`), registered
via `app.modules.registry.ModuleOrgBundleHooks`/`ModuleProjectBundleHooks`
on this module's own `MODULE_DEFINITION` (`modules.compliance.module`)
rather than those core files importing this module directly — the same
module-self-containment goal `resolve_file_owner_project_id` already serves
one concern earlier (file-attachment authorization). Moved out of
`org_export.py`/`project_export.py` directly, where this content previously
lived as `_collect_compliance_export_data`/`_import_compliance_vocab`/
`_import_compliance_standards`/`_import_compliance_requirement_mappings`/
`_collect_project_compliance_data`/`_apply_project_compliance_data`; see
`docs/decisions.md`'s "Compliance module self-containment" entry for why.

Two bundle levels, matching this module's own established Phase 15 split
(see `modules.compliance.reports`'s identical org/project distinction):

- Organisation level (`export_org_data`/`import_org_data`/`compute_org_
  merge_conflicts`/`summarize_org_merge`, registered as `ModuleOrgBundleHooks`
  on `MODULE_DEFINITION`): standards, their versions' full requirement/
  required-action trees, the organisation's action-type/mapping-
  relationship-type vocabularies, and cross-standard requirement mappings —
  org-level reusable resources per §31 ("A Compliance Standard is not a
  Project"), consumed by `org_export.build_org_bundle`/`import_org_bundle`/
  `merge_org_bundle`.
- Project level (`export_project_data`/`import_project_data`, registered as
  `ModuleProjectBundleHooks`): a project's own compliance *assessment* —
  which standards it's assigned to, its per-requirement applicability/
  status/approval state, evidence (with files, revalidation history, and
  requirement/required-action linkage), and its own project-level review
  history — consumed by `project_export.collect_project_data`/
  `apply_project_data`. The assigned *standard* itself is never re-embedded
  here; a project bundle instead records a portable `(standard reference,
  version label)` key and resolves it against whatever the *target*
  organisation already has at import time (skipped with a warning if no
  match exists there).

Every cross-reference uses a portable key (a requirement's synthetic
export-scoped `ref`, an evidence row's `ref`, `_requirement_key`/`_required_
action_key`'s `(reference, name)`/`name` matching keys), never a raw
database id — mirroring every other cross-reference in this bundle format
(`org_export`/`project_export`'s own established convention).

Phase 21 (docs/compliance-module-plan.md, §29) adds a third, narrower level:
`export_standard_data`/`import_standard_data` — a single `ComplianceStandard`
as its own portable JSON document (`GET .../standards/{id}/export`/
`POST .../standards/import` on `router.py`), distinct from the whole-org
bundle above. See those two functions' own docstrings for the full design
(the `STANDARD_EXPORT_FORMAT` document shape, `" (imported)"` reference-
collision handling, and how a cross-standard requirement mapping's
"external" side is recorded/resolved).

External dependencies: `app.services.bundle_common` (`UserResolver`/
`BundleImportWarnings`/`import_bundled_file`) directly, the same way
`project_router.py` already calls `app.services.files.upload_file` directly
from module code rather than through a core wrapper — see that router's own
module docstring for why that precedent applies here too.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.user import User
from app.modules.compliance.enums import (
    ComplianceApplicability,
    ComplianceApprovalState,
    ComplianceReviewOutcome,
    ComplianceReviewStatus,
    ComplianceStandardVersionStatus,
    ComplianceStatus,
)
from app.modules.compliance.models import (
    ComplianceActionTypeDefinition,
    ComplianceEvidence,
    ComplianceEvidenceActionLink,
    ComplianceEvidenceFile,
    ComplianceEvidenceRequirementLink,
    ComplianceEvidenceRevalidation,
    ComplianceMappingRelationshipTypeDefinition,
    ComplianceRequiredAction,
    ComplianceRequiredActionAssessment,
    ComplianceRequirement,
    ComplianceRequirementMapping,
    ComplianceReview,
    ComplianceReviewEvidenceLink,
    ComplianceStandard,
    ComplianceStandardVersion,
    ProjectCompliance,
    ProjectComplianceRequirement,
)
from app.modules.compliance.service import materialize_assessment_rows
from app.services.bundle_common import BundleImportWarnings, UserResolver, import_bundled_file

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.project import Project

# Valid `resolutions` values `org_export.merge_org_bundle` accepts for a
# `"compliance_standard"` conflict — merged into that function's own
# `_resolution_choices_by_kind` via `ModuleOrgBundleHooks.merge_resolution_
# choices`.
ORG_MERGE_RESOLUTION_CHOICES: Mapping[str, frozenset[str]] = {
    "compliance_standard": frozenset({"skip", "import_as_copy"}),
}


def _j(value: Any) -> Any:
    """Renders a value for embedding in the bundle's JSON — datetimes/dates
    as ISO strings (parsed back with `datetime.fromisoformat`/`date.
    fromisoformat` on import), enums as their plain string value, else
    unchanged. Mirrors `org_export`/`project_export`'s own identical
    private helper."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _requirement_key(requirement: ComplianceRequirement) -> str:
    """A within-version matching key for a `ComplianceRequirement` —
    `(reference, name)`, since requirement rows carry no cross-deployment-
    portable identifier of their own (unlike a core `Requirement`'s
    `unique_code`). Two requirements sharing both an identical `reference`
    and `name` within one version (not prevented by any DB constraint, but
    not a realistic authoring pattern either) would collide here, the same
    documented limitation `project_export.apply_project_data`'s
    prefix-based component/category matching already carries."""
    return f"{requirement.reference or ''}|{requirement.name}"


def _required_action_key(action: ComplianceRequiredAction) -> str:
    """A within-requirement matching key for a `ComplianceRequiredAction` —
    just its `name`, mirroring `_requirement_key`'s identical reasoning one
    level down (a required action has no other portable identifying field)."""
    return action.name


def export_org_data(db: Session, org: Organization) -> dict[str, Any]:
    """`ModuleOrgBundleHooks.export` — collects this organisation's
    Compliance Module content (§29) as a plain dict — every standard, with
    every version's full requirement/required-action tree, plus the
    organisation's action-type and mapping-relationship-type vocabularies
    and its cross-standard requirement mappings.

    Every requirement is assigned a synthetic, export-scoped `ref`
    (`"<standard reference>::v<version number>::<n>"`) so `parent_
    requirement_id`, `cloned_from_requirement_id` (which may point at a
    requirement in an *earlier* version of the same standard — see
    `models.py`'s own Phase 11 notes), and requirement-mapping endpoints
    never carry a raw database id, mirroring every other cross-reference in
    this bundle format. `standard.versions` is walked in its own natural
    `version_number` order (see `ComplianceStandard.versions`'s own
    `order_by`), so an older version's requirements always get their `ref`
    assigned before a later version that clones from them is processed —
    `cloned_from_requirement_id` can therefore always be resolved to an
    already-known ref, never a forward reference.

    Includes archived standards/versions/mappings — this module's own
    established "export everything, let the reader filter" convention
    (`report_templates`/`members` aren't filtered by any lifecycle flag
    either), since a bundle is a backup/migration artefact, not a live
    listing.
    """
    standards = list(db.scalars(select(ComplianceStandard).where(ComplianceStandard.organization_id == org.id)))
    action_types = list(
        db.scalars(select(ComplianceActionTypeDefinition).where(ComplianceActionTypeDefinition.organization_id == org.id))
    )
    relationship_types = list(
        db.scalars(
            select(ComplianceMappingRelationshipTypeDefinition).where(
                ComplianceMappingRelationshipTypeDefinition.organization_id == org.id
            )
        )
    )
    action_type_name_by_id = {t.id: t.name for t in action_types}
    relationship_type_name_by_id = {t.id: t.name for t in relationship_types}

    # One deployment-wide user lookup for every *_id encountered below,
    # mirroring `project_export.collect_project_data`'s own established
    # "single batched lookup, not N+1" convention.
    user_ids: set[UUID] = set()
    for s in standards:
        user_ids |= {s.owner_id, s.creator_id}
        if s.archived_by:
            user_ids.add(s.archived_by)
    requirement_ref_by_id: dict[UUID, str] = {}
    standards_json = []
    all_requirements: list[ComplianceRequirement] = []
    all_required_actions: list[ComplianceRequiredAction] = []

    for standard in standards:
        versions_json = []
        for version in standard.versions:
            user_ids.add(version.created_by)
            if version.published_by:
                user_ids.add(version.published_by)
            if version.retired_by:
                user_ids.add(version.retired_by)
            requirements = list(
                db.scalars(
                    select(ComplianceRequirement).where(ComplianceRequirement.standard_version_id == version.id)
                ).all()
            )
            all_requirements.extend(requirements)
            for i, r in enumerate(requirements):
                requirement_ref_by_id[r.id] = f"{standard.reference}::v{version.version_number}::{i + 1}"
                user_ids.add(r.created_by)
                if r.last_clarified_by:
                    user_ids.add(r.last_clarified_by)
            required_actions_by_requirement: dict[UUID, list[ComplianceRequiredAction]] = {}
            if requirements:
                actions = list(
                    db.scalars(
                        select(ComplianceRequiredAction).where(
                            ComplianceRequiredAction.requirement_id.in_([r.id for r in requirements])
                        )
                    ).all()
                )
                all_required_actions.extend(actions)
                for a in actions:
                    user_ids.add(a.created_by)
                    required_actions_by_requirement.setdefault(a.requirement_id, []).append(a)

            requirements_json = []
            for r in requirements:
                requirements_json.append({
                    "ref": requirement_ref_by_id[r.id],
                    "parent_ref": requirement_ref_by_id.get(r.parent_requirement_id) if r.parent_requirement_id else None,
                    "cloned_from_ref": (
                        requirement_ref_by_id.get(r.cloned_from_requirement_id) if r.cloned_from_requirement_id else None
                    ),
                    "reference": r.reference, "name": r.name, "description": r.description, "reasoning": r.reasoning,
                    "sort_order": r.sort_order, "created_by_email": None,  # filled in below once emails are resolved
                    "_created_by": r.created_by,
                    "clarification_count": r.clarification_count, "last_clarified_at": _j(r.last_clarified_at),
                    "last_clarification_note": r.last_clarification_note, "_last_clarified_by": r.last_clarified_by,
                    "required_actions": [
                        {
                            "action_type_name": action_type_name_by_id.get(a.action_type_id, ""),
                            "name": a.name, "description": a.description, "is_mandatory": a.is_mandatory,
                            "sort_order": a.sort_order, "_created_by": a.created_by,
                        }
                        for a in sorted(required_actions_by_requirement.get(r.id, []), key=lambda a: a.sort_order)
                    ],
                })
            versions_json.append({
                "version_number": version.version_number, "version_label": version.version_label,
                "status": version.status.value, "effective_date": _j(version.effective_date),
                "change_note": version.change_note, "summary": version.summary, "_created_by": version.created_by,
                "published_at": _j(version.published_at), "_published_by": version.published_by,
                "retired_at": _j(version.retired_at), "_retired_by": version.retired_by,
                "requirements": requirements_json,
            })
        standards_json.append({
            "reference": standard.reference, "name": standard.name, "description": standard.description,
            "issuing_organisation": standard.issuing_organisation, "_owner": standard.owner_id,
            "_creator": standard.creator_id, "is_archived": standard.is_archived,
            "archived_at": _j(standard.archived_at), "_archived_by": standard.archived_by,
            "versions": versions_json,
        })

    mappings = list(
        db.scalars(select(ComplianceRequirementMapping).where(ComplianceRequirementMapping.organization_id == org.id))
    )
    for m in mappings:
        user_ids.add(m.created_by)
        if m.archived_by:
            user_ids.add(m.archived_by)
    mappings_json = [
        {
            "from_ref": requirement_ref_by_id.get(m.from_requirement_id),
            "to_ref": requirement_ref_by_id.get(m.to_requirement_id),
            "relationship_type_name": relationship_type_name_by_id.get(m.relationship_type_id, ""),
            "notes": m.notes, "_created_by": m.created_by, "is_archived": m.is_archived,
            "archived_at": _j(m.archived_at), "_archived_by": m.archived_by,
        }
        for m in mappings
        if m.from_requirement_id in requirement_ref_by_id and m.to_requirement_id in requirement_ref_by_id
    ]

    user_ids.discard(None)
    email_by_id = {u.id: u.email for u in db.scalars(select(User).where(User.id.in_(user_ids)))} if user_ids else {}

    def email(user_id: UUID | None) -> str | None:
        return email_by_id.get(user_id) if user_id else None

    # Second pass: resolve every `_owner`/`_creator`/`_created_by`/
    # `_archived_by`/`_published_by`/`_retired_by` placeholder above into
    # its email, now that `email_by_id` exists — done as a rewrite rather
    # than threading `email_by_id` through the nested loops above, since
    # this bundle format's own established convention (`project_export`) is
    # to build the raw structure first and resolve emails via one shared
    # closure at the point of final assembly.
    for standard_json in standards_json:
        standard_json["owner_email"] = email(standard_json.pop("_owner"))
        standard_json["creator_email"] = email(standard_json.pop("_creator"))
        standard_json["archived_by_email"] = email(standard_json.pop("_archived_by"))
        for version_json in standard_json["versions"]:
            version_json["created_by_email"] = email(version_json.pop("_created_by"))
            version_json["published_by_email"] = email(version_json.pop("_published_by"))
            version_json["retired_by_email"] = email(version_json.pop("_retired_by"))
            for requirement_json in version_json["requirements"]:
                requirement_json["created_by_email"] = email(requirement_json.pop("_created_by"))
                requirement_json["last_clarified_by_email"] = email(requirement_json.pop("_last_clarified_by"))
                for action_json in requirement_json["required_actions"]:
                    action_json["created_by_email"] = email(action_json.pop("_created_by"))
    for mapping_json in mappings_json:
        mapping_json["created_by_email"] = email(mapping_json.pop("_created_by"))
        mapping_json["archived_by_email"] = email(mapping_json.pop("_archived_by"))

    return {
        "compliance_action_types": [{"name": t.name, "sort_order": t.sort_order} for t in action_types],
        "compliance_mapping_relationship_types": [
            {"name": t.name, "sort_order": t.sort_order, "implies_equivalence": t.implies_equivalence}
            for t in relationship_types
        ],
        "compliance_standards": standards_json,
        "compliance_requirement_mappings": mappings_json,
    }


def compute_org_merge_conflicts(db: Session, target_org: Organization, data: dict[str, Any]) -> list[dict[str, Any]]:
    """`ModuleOrgBundleHooks.compute_merge_conflicts` — this module's own
    name-collision conflicts for `org_export.detect_merge_conflicts`/
    `merge_org_bundle`: a bundle standard whose `reference` collides (case-
    insensitively) with one `target_org` already has. Mirrors `org_export.
    _compute_merge_conflicts`'s identical project/report-template checks."""
    existing_standards_by_reference = {
        s.reference.strip().lower(): s
        for s in db.scalars(select(ComplianceStandard).where(ComplianceStandard.organization_id == target_org.id))
    }
    conflicts: list[dict[str, Any]] = []
    for s in data.get("compliance_standards", []):
        existing = existing_standards_by_reference.get(s["reference"].strip().lower())
        if existing is not None:
            conflicts.append({
                "id": f"compliance_standard:{s['reference']}", "kind": "compliance_standard",
                "name": s["reference"], "existing_id": str(existing.id),
            })
    return conflicts


def summarize_org_merge(
    data: dict[str, Any], conflicts: list[dict[str, Any]], resolutions: dict[str, str]
) -> dict[str, int]:
    """`ModuleOrgBundleHooks.summarize_merge` — this module's own named
    counts for `org_export.merge_org_bundle`'s returned/audit-logged summary."""
    standard_conflicts = [c for c in conflicts if c["kind"] == "compliance_standard"]
    skipped = sum(1 for c in standard_conflicts if resolutions[c["id"]] == "skip")
    return {
        "compliance_standards_imported": len(data.get("compliance_standards", [])) - skipped,
        "compliance_standards_skipped": skipped,
    }


def _import_compliance_vocab(db: Session, org: Organization, data: dict[str, Any]) -> None:
    """Creates this organisation's compliance action-type and mapping-
    relationship-type vocabularies from a bundle. Always purely additive by
    name, for both `import_org_bundle` (a fresh org never already has one,
    so every entry is created) and `merge_org_bundle` (a bundle entry whose
    name matches one the target org already has is left completely alone,
    never overwritten) — mirroring `org_export._import_org_groups`'s own
    "reuse by name" precedent: these are just organisation-chosen vocabulary
    labels with no history or sub-content, and overwriting `implies_
    equivalence` on an existing type as a side effect of an unrelated import
    would silently change a Compliance Manager's own prior decision about it
    (see `models.py`'s own Phase 11 notes on why that flag defaults `False`
    and is deliberately never inferred). Must run before `_import_
    compliance_standards`, whose required actions resolve `action_type_name`
    against the rows this creates."""
    existing_action_type_names = {
        t.name.strip().lower()
        for t in db.scalars(select(ComplianceActionTypeDefinition).where(ComplianceActionTypeDefinition.organization_id == org.id))
    }
    for t in data.get("compliance_action_types", []):
        if t["name"].strip().lower() in existing_action_type_names:
            continue
        db.add(ComplianceActionTypeDefinition(organization_id=org.id, name=t["name"], sort_order=t.get("sort_order", 0)))

    existing_relationship_type_names = {
        t.name.strip().lower()
        for t in db.scalars(
            select(ComplianceMappingRelationshipTypeDefinition).where(
                ComplianceMappingRelationshipTypeDefinition.organization_id == org.id
            )
        )
    }
    for t in data.get("compliance_mapping_relationship_types", []):
        if t["name"].strip().lower() in existing_relationship_type_names:
            continue
        db.add(ComplianceMappingRelationshipTypeDefinition(
            organization_id=org.id, name=t["name"], sort_order=t.get("sort_order", 0),
            implies_equivalence=t.get("implies_equivalence", False),
        ))
    db.flush()


def _import_compliance_standards(
    db: Session, org: Organization, data: dict[str, Any], users: UserResolver, warnings: BundleImportWarnings,
    *, resolutions: dict[str, str] | None,
) -> dict[str, UUID]:
    """Creates compliance standards — with every version's full requirement/
    required-action tree — from a bundle. `resolutions=None` (`import_org_
    bundle`): every standard is new, since a brand-new organisation can't
    already have one with the same `reference`. Otherwise (`merge_org_
    bundle`): a bundle standard whose `reference` collides with one the
    target org already has is skipped (`"skip"`) or imported as a distinct
    copy under a renamed reference (`"import_as_copy"`) per
    `resolutions[f"compliance_standard:{reference}"]` — never overwritten in
    place, mirroring `org_export._import_projects`'s identical reasoning: a
    standard's versions/requirements/required actions are real content an
    in-place replace would destroy, unlike a report template's pure
    presentation config.

    Must run after `_import_compliance_vocab` (required-action type names
    are resolved against its output; an unresolvable name — should not
    happen for a bundle this application produced itself — is skipped with
    a warning rather than failing the whole import).

    Args:
        db, org, data: As elsewhere in this module.
        users: The shared `UserResolver` for this import.
        warnings: Accumulates human-readable import warnings.
        resolutions: See above.

    Returns:
        Every imported requirement's bundle `ref` -> its new database id,
        for `_import_compliance_requirement_mappings` (which runs after
        every standard has been imported) to resolve `from_ref`/`to_ref`
        against.
    """
    existing_by_reference: dict[str, ComplianceStandard] = {}
    if resolutions is not None:
        existing_by_reference = {
            s.reference.strip().lower(): s
            for s in db.scalars(select(ComplianceStandard).where(ComplianceStandard.organization_id == org.id))
        }
    action_type_id_by_name = {
        t.name.strip().lower(): t.id
        for t in db.scalars(select(ComplianceActionTypeDefinition).where(ComplianceActionTypeDefinition.organization_id == org.id))
    }

    requirement_id_by_ref: dict[str, UUID] = {}
    pending_parent_links: list[tuple[UUID, str]] = []
    pending_clone_links: list[tuple[UUID, str]] = []

    for s in data.get("compliance_standards", []):
        reference = s["reference"]
        if resolutions is not None and reference.strip().lower() in existing_by_reference:
            if resolutions.get(f"compliance_standard:{reference}") == "skip":
                continue
            reference = f"{reference} (imported)"

        standard = ComplianceStandard(
            organization_id=org.id, reference=reference, name=s["name"], description=s.get("description", ""),
            issuing_organisation=s.get("issuing_organisation"),
            owner_id=users.resolve(s.get("owner_email"), required=True, context=f"Compliance standard {reference} owner"),
            creator_id=users.resolve(s.get("creator_email"), required=True, context=f"Compliance standard {reference} creator"),
            is_archived=s.get("is_archived", False), archived_at=_dt(s.get("archived_at")),
            archived_by=users.resolve(s.get("archived_by_email"), required=False, context=f"Compliance standard {reference} archiver"),
        )
        db.add(standard)
        db.flush()

        for v in s.get("versions", []):
            version = ComplianceStandardVersion(
                standard_id=standard.id, version_number=v["version_number"], version_label=v["version_label"],
                status=ComplianceStandardVersionStatus(v["status"]), effective_date=_date(v.get("effective_date")),
                change_note=v.get("change_note", ""), summary=v.get("summary", ""),
                created_by=users.resolve(
                    v.get("created_by_email"), required=True, context=f"Standard {reference} v{v['version_label']} author"
                ),
                published_at=_dt(v.get("published_at")),
                published_by=users.resolve(
                    v.get("published_by_email"), required=False, context=f"Standard {reference} v{v['version_label']} publisher"
                ),
                retired_at=_dt(v.get("retired_at")),
                retired_by=users.resolve(
                    v.get("retired_by_email"), required=False, context=f"Standard {reference} v{v['version_label']} retirer"
                ),
            )
            db.add(version)
            db.flush()

            for r in v.get("requirements", []):
                requirement = ComplianceRequirement(
                    standard_version_id=version.id, parent_requirement_id=None,  # linked in the second pass below
                    reference=r.get("reference"), name=r["name"], description=r.get("description", ""),
                    reasoning=r.get("reasoning", ""), sort_order=r.get("sort_order", 0),
                    created_by=users.resolve(r.get("created_by_email"), required=True, context=f"Requirement {r['ref']} author"),
                    clarification_count=r.get("clarification_count", 0),
                    last_clarified_at=_dt(r.get("last_clarified_at")),
                    last_clarification_note=r.get("last_clarification_note", ""),
                    last_clarified_by=users.resolve(
                        r.get("last_clarified_by_email"), required=False, context=f"Requirement {r['ref']} last clarifier"
                    ),
                )
                db.add(requirement)
                db.flush()
                requirement_id_by_ref[r["ref"]] = requirement.id
                if r.get("parent_ref"):
                    pending_parent_links.append((requirement.id, r["parent_ref"]))
                if r.get("cloned_from_ref"):
                    pending_clone_links.append((requirement.id, r["cloned_from_ref"]))

                for a in r.get("required_actions", []):
                    action_type_id = action_type_id_by_name.get((a.get("action_type_name") or "").strip().lower())
                    if action_type_id is None:
                        warnings.add(
                            f"Required action '{a['name']}' on requirement {r.get('reference') or r['name']!r} "
                            f"references an action type ({a.get('action_type_name')!r}) that doesn't exist in the "
                            "target organisation and was skipped."
                        )
                        continue
                    db.add(ComplianceRequiredAction(
                        requirement_id=requirement.id, action_type_id=action_type_id, name=a["name"],
                        description=a.get("description", ""), is_mandatory=a.get("is_mandatory", True),
                        sort_order=a.get("sort_order", 0),
                        created_by=users.resolve(
                            a.get("created_by_email"), required=True, context=f"Required action '{a['name']}' author"
                        ),
                    ))

    # Second pass: `parent_requirement_id`/`cloned_from_requirement_id` can
    # only be wired up once every requirement in the bundle has been created
    # (a clone may point at a requirement in an earlier version processed
    # earlier in the loop above, but a parent link within the same version
    # is created in list order, which does not guarantee parents precede
    # children) — mirrors `project_export.apply_project_data`'s own
    # identical two-pass shape for `RequirementVersion.change_request_id`.
    for requirement_id, parent_ref in pending_parent_links:
        parent_id = requirement_id_by_ref.get(parent_ref)
        if parent_id is not None:
            db.get(ComplianceRequirement, requirement_id).parent_requirement_id = parent_id
    for requirement_id, cloned_from_ref in pending_clone_links:
        cloned_from_id = requirement_id_by_ref.get(cloned_from_ref)
        if cloned_from_id is not None:
            db.get(ComplianceRequirement, requirement_id).cloned_from_requirement_id = cloned_from_id

    return requirement_id_by_ref


def _import_compliance_requirement_mappings(
    db: Session, org: Organization, data: dict[str, Any], users: UserResolver,
    requirement_id_by_ref: dict[str, UUID], warnings: BundleImportWarnings,
) -> None:
    """Creates cross-standard/cross-version requirement mappings from a
    bundle, once every standard has been imported (`_import_compliance_
    standards`'s returned `requirement_id_by_ref`). A mapping whose `from_
    ref`/`to_ref` wasn't imported (e.g. its owning standard was `"skip"`ped
    during a merge) or whose `relationship_type_name` has no match in the
    target organisation is skipped with a warning, mirroring this module's
    established `requirement_link_type_forward_name` handling in `services.
    project_export`."""
    relationship_type_id_by_name = {
        t.name.strip().lower(): t.id
        for t in db.scalars(
            select(ComplianceMappingRelationshipTypeDefinition).where(
                ComplianceMappingRelationshipTypeDefinition.organization_id == org.id
            )
        )
    }
    for m in data.get("compliance_requirement_mappings", []):
        from_id = requirement_id_by_ref.get(m.get("from_ref"))
        to_id = requirement_id_by_ref.get(m.get("to_ref"))
        relationship_type_id = relationship_type_id_by_name.get((m.get("relationship_type_name") or "").strip().lower())
        if from_id is None or to_id is None or relationship_type_id is None or from_id == to_id:
            warnings.add(
                f"A compliance requirement mapping ({m.get('relationship_type_name')!r}) could not be fully "
                "resolved in the target organisation and was skipped."
            )
            continue
        db.add(ComplianceRequirementMapping(
            organization_id=org.id, from_requirement_id=from_id, to_requirement_id=to_id,
            relationship_type_id=relationship_type_id, notes=m.get("notes", ""),
            created_by=users.resolve(m.get("created_by_email"), required=True, context="Compliance requirement mapping creator"),
            is_archived=m.get("is_archived", False), archived_at=_dt(m.get("archived_at")),
            archived_by=users.resolve(m.get("archived_by_email"), required=False, context="Compliance requirement mapping archiver"),
        ))


def import_org_data(
    db: Session, org: Organization, data: dict[str, Any], users: UserResolver, warnings: BundleImportWarnings,
    resolutions: dict[str, str] | None,
) -> None:
    """`ModuleOrgBundleHooks.import_` — creates this organisation's
    compliance vocabularies, standards (with every version's full
    requirement/required-action tree), and cross-standard requirement
    mappings from a bundle, in that order (each stage's own docstring below
    explains why). Bundles the three formerly-separate `org_export.py` call
    sites (`_import_compliance_vocab`/`_import_compliance_standards`/
    `_import_compliance_requirement_mappings`) into the single hook `Module
    OrgBundleHooks.import_` declares, since `_import_compliance_standards`'s
    returned `requirement_id_by_ref` has no other consumer once `_import_
    compliance_requirement_mappings` has run."""
    _import_compliance_vocab(db, org, data)
    requirement_id_by_ref = _import_compliance_standards(db, org, data, users, warnings, resolutions=resolutions)
    _import_compliance_requirement_mappings(db, org, data, users, requirement_id_by_ref, warnings)


# --- Phase 21: standard-level import/export -----------------------------------
#
# A narrower sibling to `export_org_data`/`import_org_data` above: a single
# `ComplianceStandard` (with every version's full requirement/required-
# action tree) as its own portable, self-contained JSON document — for
# backing up or transferring just one standard, rather than an entire
# organisation. See docs/compliance-module-plan.md's Phase 21 spec for the
# full design; the short version is in each function's own docstring below.

STANDARD_EXPORT_FORMAT = "reqtrackmanager.compliance_standard.v1"


def _mapping_side_json(
    db: Session, requirement_id: UUID, requirement_ref_by_id: dict[UUID, str]
) -> dict[str, Any]:
    """One side (`from`/`to`) of a `ComplianceRequirementMapping` entry in
    `export_standard_data`'s output — a local `ref` when `requirement_id`
    belongs to the standard being exported, else an `external` triple
    (`standard_reference`, `version_label`, `requirement_key`) that
    `import_standard_data` attempts to resolve against whatever the
    *target* organisation already has (see that function's own docstring)."""
    ref = requirement_ref_by_id.get(requirement_id)
    if ref is not None:
        return {"ref": ref, "external": None}
    requirement = db.get(ComplianceRequirement, requirement_id)
    version = db.get(ComplianceStandardVersion, requirement.standard_version_id)
    other_standard = db.get(ComplianceStandard, version.standard_id)
    return {
        "ref": None,
        "external": {
            "standard_reference": other_standard.reference, "version_label": version.version_label,
            "requirement_key": _requirement_key(requirement),
        },
    }


def export_standard_data(db: Session, standard: ComplianceStandard) -> dict[str, Any]:
    """Exports a single `ComplianceStandard` (Phase 21, §29) as a portable,
    self-contained JSON document distinct from `export_org_data`'s whole-
    organisation bundle — every version's full requirement/required-action
    tree, plus only the subset of the organisation's action-type/mapping-
    relationship-type vocabularies actually referenced by this standard's
    own required actions/requirement mappings (not the whole
    organisation's vocabulary).

    Reuses `export_org_data`'s exact synthetic per-requirement `ref`
    convention (`"<standard reference>::v<version number>::<n>"`,
    `parent_ref`/`cloned_from_ref` resolved the same way) and its
    `compliance_action_types`/`compliance_mapping_relationship_types`
    top-level key names, so `import_standard_data` can hand this
    document's own `data` straight to `_import_compliance_vocab` unchanged
    — "reuse `export.py`'s existing portable-key convention wholesale" per
    this phase's own spec.

    A requirement mapping (§19) touching this standard is always included,
    even when its *other* side belongs to a different standard — that side
    is recorded via `_mapping_side_json`'s `external` triple rather than a
    local `ref` (which only covers requirements this document itself
    carries); see `import_standard_data`'s own docstring for how that's
    resolved (or dropped with a warning) on the way back in.
    """
    requirement_ref_by_id: dict[UUID, str] = {}
    per_version: list[
        tuple[ComplianceStandardVersion, list[ComplianceRequirement], dict[UUID, list[ComplianceRequiredAction]]]
    ] = []
    all_required_actions: list[ComplianceRequiredAction] = []
    user_ids: set[UUID | None] = {standard.owner_id, standard.creator_id, standard.archived_by}

    for version in standard.versions:
        user_ids |= {version.created_by, version.published_by, version.retired_by}
        requirements = list(
            db.scalars(select(ComplianceRequirement).where(ComplianceRequirement.standard_version_id == version.id)).all()
        )
        for i, r in enumerate(requirements):
            requirement_ref_by_id[r.id] = f"{standard.reference}::v{version.version_number}::{i + 1}"
            user_ids.add(r.created_by)
            user_ids.add(r.last_clarified_by)
        required_actions_by_requirement: dict[UUID, list[ComplianceRequiredAction]] = {}
        if requirements:
            actions = list(
                db.scalars(
                    select(ComplianceRequiredAction).where(
                        ComplianceRequiredAction.requirement_id.in_([r.id for r in requirements])
                    )
                ).all()
            )
            all_required_actions.extend(actions)
            for a in actions:
                user_ids.add(a.created_by)
                required_actions_by_requirement.setdefault(a.requirement_id, []).append(a)
        per_version.append((version, requirements, required_actions_by_requirement))

    # Only the action types this standard's own required actions actually
    # use, resolved by name after the loop above (mirrors `export_org_
    # data`'s own `action_type_name_by_id`, scoped down) — "not the whole
    # org's vocabulary" per this phase's own spec.
    action_type_ids = {a.action_type_id for a in all_required_actions}
    action_types_used = (
        list(db.scalars(select(ComplianceActionTypeDefinition).where(ComplianceActionTypeDefinition.id.in_(action_type_ids))))
        if action_type_ids else []
    )
    action_type_name_by_id = {t.id: t.name for t in action_types_used}

    versions_json = []
    for version, requirements, required_actions_by_requirement in per_version:
        requirements_json = []
        for r in requirements:
            requirements_json.append({
                "ref": requirement_ref_by_id[r.id],
                "parent_ref": requirement_ref_by_id.get(r.parent_requirement_id) if r.parent_requirement_id else None,
                "cloned_from_ref": (
                    requirement_ref_by_id.get(r.cloned_from_requirement_id) if r.cloned_from_requirement_id else None
                ),
                "reference": r.reference, "name": r.name, "description": r.description, "reasoning": r.reasoning,
                "sort_order": r.sort_order, "_created_by": r.created_by,
                "clarification_count": r.clarification_count, "last_clarified_at": _j(r.last_clarified_at),
                "last_clarification_note": r.last_clarification_note, "_last_clarified_by": r.last_clarified_by,
                "required_actions": [
                    {
                        "action_type_name": action_type_name_by_id.get(a.action_type_id, ""),
                        "name": a.name, "description": a.description, "is_mandatory": a.is_mandatory,
                        "sort_order": a.sort_order, "_created_by": a.created_by,
                    }
                    for a in sorted(required_actions_by_requirement.get(r.id, []), key=lambda a: a.sort_order)
                ],
            })
        versions_json.append({
            "version_number": version.version_number, "version_label": version.version_label,
            "status": version.status.value, "effective_date": _j(version.effective_date),
            "change_note": version.change_note, "summary": version.summary, "_created_by": version.created_by,
            "published_at": _j(version.published_at), "_published_by": version.published_by,
            "retired_at": _j(version.retired_at), "_retired_by": version.retired_by,
            "requirements": requirements_json,
        })

    mappings = (
        list(
            db.scalars(
                select(ComplianceRequirementMapping).where(
                    ComplianceRequirementMapping.organization_id == standard.organization_id,
                    (
                        ComplianceRequirementMapping.from_requirement_id.in_(list(requirement_ref_by_id))
                        | ComplianceRequirementMapping.to_requirement_id.in_(list(requirement_ref_by_id))
                    ),
                )
            )
        )
        if requirement_ref_by_id else []
    )
    relationship_type_ids = {m.relationship_type_id for m in mappings}
    relationship_types_used = (
        list(
            db.scalars(
                select(ComplianceMappingRelationshipTypeDefinition).where(
                    ComplianceMappingRelationshipTypeDefinition.id.in_(relationship_type_ids)
                )
            )
        )
        if relationship_type_ids else []
    )
    relationship_type_name_by_id = {t.id: t.name for t in relationship_types_used}
    for m in mappings:
        user_ids |= {m.created_by, m.archived_by}
    mappings_json = [
        {
            "from": _mapping_side_json(db, m.from_requirement_id, requirement_ref_by_id),
            "to": _mapping_side_json(db, m.to_requirement_id, requirement_ref_by_id),
            "relationship_type_name": relationship_type_name_by_id.get(m.relationship_type_id, ""),
            "notes": m.notes, "_created_by": m.created_by, "is_archived": m.is_archived,
            "archived_at": _j(m.archived_at), "_archived_by": m.archived_by,
        }
        for m in mappings
    ]

    user_ids.discard(None)
    email_by_id = {u.id: u.email for u in db.scalars(select(User).where(User.id.in_(user_ids)))} if user_ids else {}

    def email(user_id: UUID | None) -> str | None:
        return email_by_id.get(user_id) if user_id else None

    for version_json in versions_json:
        version_json["created_by_email"] = email(version_json.pop("_created_by"))
        version_json["published_by_email"] = email(version_json.pop("_published_by"))
        version_json["retired_by_email"] = email(version_json.pop("_retired_by"))
        for requirement_json in version_json["requirements"]:
            requirement_json["created_by_email"] = email(requirement_json.pop("_created_by"))
            requirement_json["last_clarified_by_email"] = email(requirement_json.pop("_last_clarified_by"))
            for action_json in requirement_json["required_actions"]:
                action_json["created_by_email"] = email(action_json.pop("_created_by"))
    for mapping_json in mappings_json:
        mapping_json["created_by_email"] = email(mapping_json.pop("_created_by"))
        mapping_json["archived_by_email"] = email(mapping_json.pop("_archived_by"))

    return {
        "format": STANDARD_EXPORT_FORMAT,
        "exported_at": _j(datetime.now(UTC)),
        "compliance_action_types": [{"name": t.name, "sort_order": t.sort_order} for t in action_types_used],
        "compliance_mapping_relationship_types": [
            {"name": t.name, "sort_order": t.sort_order, "implies_equivalence": t.implies_equivalence}
            for t in relationship_types_used
        ],
        "standard": {
            "reference": standard.reference, "name": standard.name, "description": standard.description,
            "issuing_organisation": standard.issuing_organisation,
            "owner_email": email(standard.owner_id), "creator_email": email(standard.creator_id),
            "is_archived": standard.is_archived, "archived_at": _j(standard.archived_at),
            "archived_by_email": email(standard.archived_by),
            "versions": versions_json,
        },
        "requirement_mappings": mappings_json,
    }


def _resolve_mapping_side(
    db: Session, org: Organization, side: dict[str, Any], requirement_id_by_ref: dict[str, UUID]
) -> UUID | None:
    """Resolves one `_mapping_side_json`-shaped side of a requirement
    mapping during import — a local `ref` against this import's own
    `requirement_id_by_ref`, or an `external` triple against `org`'s
    existing standards/versions/requirements by name (see `import_standard_
    data`'s own docstring for why an external side may simply not resolve)."""
    if side.get("ref"):
        return requirement_id_by_ref.get(side["ref"])
    external = side.get("external")
    if not external:
        return None
    target_standard = db.scalar(
        select(ComplianceStandard).where(
            ComplianceStandard.organization_id == org.id, ComplianceStandard.reference == external["standard_reference"]
        )
    )
    if target_standard is None:
        return None
    target_version = db.scalar(
        select(ComplianceStandardVersion).where(
            ComplianceStandardVersion.standard_id == target_standard.id,
            ComplianceStandardVersion.version_label == external["version_label"],
        )
    )
    if target_version is None:
        return None
    for r in db.scalars(select(ComplianceRequirement).where(ComplianceRequirement.standard_version_id == target_version.id)):
        if _requirement_key(r) == external["requirement_key"]:
            return r.id
    return None


def import_standard_data(
    db: Session, org: Organization, data: dict[str, Any], users: UserResolver, warnings: BundleImportWarnings,
    *, resolution: str | None,
) -> tuple[ComplianceStandard | None, bool]:
    """Creates a single `ComplianceStandard` — with every version's full
    requirement/required-action tree, always re-created as `DRAFT`
    regardless of the exported version's own status — from an
    `export_standard_data` document (Phase 21, §29), in `org`. §4/§31: an
    imported standard must be reviewed and re-published locally before it
    governs any project, never silently live — this is the one deliberate
    departure from the export's own recorded `status`/`published_*`/
    `retired_*` fields; every other field is carried over as exported.

    Reference-collision handling mirrors the whole-org merge precedent
    (`ORG_MERGE_RESOLUTION_CHOICES`, `_import_compliance_standards`): if
    `org` already has a standard whose `reference` matches (case-
    insensitively), `resolution` must be `"skip"` (nothing is created;
    returns `(None, True)`) or `"import_as_copy"` (the reference gets the
    same `" (imported)"` suffix `_import_compliance_standards` already uses
    for the identical collision one level up). A `None` resolution with a
    real collision raises 409 so the caller can ask the user which to
    choose — this module's own narrower alternative to the full org-bundle
    preview/merge two-step, appropriate here since there is only ever one
    possible collision (this standard's own reference), unlike an org
    bundle's many.

    A `requirement_mappings` entry (§19) whose `from`/`to` side is
    `external` (pointing at a requirement outside this document, i.e. in a
    *different* standard) is resolved against `org`'s own existing
    standards by `(standard_reference, version_label, requirement_key)` —
    dropped with a warning if no match exists there, since the target
    organisation/deployment may not have that other standard at all
    (mirrors how `import_project_data` already drops an unresolvable
    standard reference with a warning).
    """
    if data.get("format") != STANDARD_EXPORT_FORMAT:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This file is not a valid compliance standard export.")

    standard_data = data["standard"]
    reference = standard_data["reference"]
    existing_by_reference = {
        s.reference.strip().lower(): s
        for s in db.scalars(select(ComplianceStandard).where(ComplianceStandard.organization_id == org.id))
    }
    if reference.strip().lower() in existing_by_reference:
        if resolution is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"A standard with reference '{reference}' already exists in this organisation. "
                "Choose whether to skip this import or import it as a copy.",
            )
        if resolution == "skip":
            return None, True
        if resolution != "import_as_copy":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "resolution must be 'skip' or 'import_as_copy'.")
        reference = f"{reference} (imported)"

    _import_compliance_vocab(db, org, data)
    action_type_id_by_name = {
        t.name.strip().lower(): t.id
        for t in db.scalars(select(ComplianceActionTypeDefinition).where(ComplianceActionTypeDefinition.organization_id == org.id))
    }
    relationship_type_id_by_name = {
        t.name.strip().lower(): t.id
        for t in db.scalars(
            select(ComplianceMappingRelationshipTypeDefinition).where(
                ComplianceMappingRelationshipTypeDefinition.organization_id == org.id
            )
        )
    }

    standard = ComplianceStandard(
        organization_id=org.id, reference=reference, name=standard_data["name"],
        description=standard_data.get("description", ""), issuing_organisation=standard_data.get("issuing_organisation"),
        owner_id=users.resolve(standard_data.get("owner_email"), required=True, context=f"Compliance standard {reference} owner"),
        creator_id=users.resolve(standard_data.get("creator_email"), required=True, context=f"Compliance standard {reference} creator"),
        is_archived=standard_data.get("is_archived", False), archived_at=_dt(standard_data.get("archived_at")),
        archived_by=users.resolve(standard_data.get("archived_by_email"), required=False, context=f"Compliance standard {reference} archiver"),
    )
    db.add(standard)
    db.flush()

    requirement_id_by_ref: dict[str, UUID] = {}
    pending_parent_links: list[tuple[UUID, str]] = []
    pending_clone_links: list[tuple[UUID, str]] = []

    for v in standard_data.get("versions", []):
        version = ComplianceStandardVersion(
            standard_id=standard.id, version_number=v["version_number"], version_label=v["version_label"],
            status=ComplianceStandardVersionStatus.DRAFT, effective_date=_date(v.get("effective_date")),
            change_note=v.get("change_note", ""), summary=v.get("summary", ""),
            created_by=users.resolve(
                v.get("created_by_email"), required=True, context=f"Standard {reference} v{v['version_label']} author"
            ),
            published_at=None, published_by=None, retired_at=None, retired_by=None,
        )
        db.add(version)
        db.flush()

        for r in v.get("requirements", []):
            requirement = ComplianceRequirement(
                standard_version_id=version.id, parent_requirement_id=None,
                reference=r.get("reference"), name=r["name"], description=r.get("description", ""),
                reasoning=r.get("reasoning", ""), sort_order=r.get("sort_order", 0),
                created_by=users.resolve(r.get("created_by_email"), required=True, context=f"Requirement {r['ref']} author"),
                clarification_count=r.get("clarification_count", 0),
                last_clarified_at=_dt(r.get("last_clarified_at")),
                last_clarification_note=r.get("last_clarification_note", ""),
                last_clarified_by=users.resolve(
                    r.get("last_clarified_by_email"), required=False, context=f"Requirement {r['ref']} last clarifier"
                ),
            )
            db.add(requirement)
            db.flush()
            requirement_id_by_ref[r["ref"]] = requirement.id
            if r.get("parent_ref"):
                pending_parent_links.append((requirement.id, r["parent_ref"]))
            if r.get("cloned_from_ref"):
                pending_clone_links.append((requirement.id, r["cloned_from_ref"]))

            for a in r.get("required_actions", []):
                action_type_id = action_type_id_by_name.get((a.get("action_type_name") or "").strip().lower())
                if action_type_id is None:
                    warnings.add(
                        f"Required action '{a['name']}' on requirement {r.get('reference') or r['name']!r} "
                        f"references an action type ({a.get('action_type_name')!r}) that doesn't exist in the "
                        "target organisation and was skipped."
                    )
                    continue
                db.add(ComplianceRequiredAction(
                    requirement_id=requirement.id, action_type_id=action_type_id, name=a["name"],
                    description=a.get("description", ""), is_mandatory=a.get("is_mandatory", True),
                    sort_order=a.get("sort_order", 0),
                    created_by=users.resolve(
                        a.get("created_by_email"), required=True, context=f"Required action '{a['name']}' author"
                    ),
                ))

    # Second pass — see `_import_compliance_standards`'s identical comment
    # one level up for why this can't be a single pass.
    for requirement_id, parent_ref in pending_parent_links:
        parent_id = requirement_id_by_ref.get(parent_ref)
        if parent_id is not None:
            db.get(ComplianceRequirement, requirement_id).parent_requirement_id = parent_id
    for requirement_id, cloned_from_ref in pending_clone_links:
        cloned_from_id = requirement_id_by_ref.get(cloned_from_ref)
        if cloned_from_id is not None:
            db.get(ComplianceRequirement, requirement_id).cloned_from_requirement_id = cloned_from_id

    for m in data.get("requirement_mappings", []):
        from_id = _resolve_mapping_side(db, org, m["from"], requirement_id_by_ref)
        to_id = _resolve_mapping_side(db, org, m["to"], requirement_id_by_ref)
        relationship_type_id = relationship_type_id_by_name.get((m.get("relationship_type_name") or "").strip().lower())
        if from_id is None or to_id is None or relationship_type_id is None or from_id == to_id:
            warnings.add(
                f"A compliance requirement mapping ({m.get('relationship_type_name')!r}) could not be fully "
                "resolved in the target organisation and was skipped."
            )
            continue
        db.add(ComplianceRequirementMapping(
            organization_id=org.id, from_requirement_id=from_id, to_requirement_id=to_id,
            relationship_type_id=relationship_type_id, notes=m.get("notes", ""),
            created_by=users.resolve(m.get("created_by_email"), required=True, context="Compliance requirement mapping creator"),
            is_archived=m.get("is_archived", False), archived_at=_dt(m.get("archived_at")),
            archived_by=users.resolve(m.get("archived_by_email"), required=False, context="Compliance requirement mapping archiver"),
        ))

    return standard, False


def export_project_data(db: Session, project: Project) -> tuple[dict[str, Any], dict[UUID, FileAsset]]:
    """`ModuleProjectBundleHooks.export` — assembles a project's Compliance
    Module content (§29) — every (including archived) `ProjectCompliance`
    assignment with its full per-requirement/per-required-action assessment
    state, every piece of evidence (with its files and revalidation
    history), and every project-level review — as the `compliance_*` keys
    merged into `project_export.collect_project_data`'s own returned dict.
    See this module's own docstring for why the assigned *standard* itself
    is referenced by portable `(standard reference, version label)` key
    rather than re-embedded, and why a requirement is matched by
    `_requirement_key` rather than a raw id.

    Standard-level `ComplianceReview` rows (`standard_id` set, not
    `project_compliance_id`) are deliberately excluded — those belong to
    the *standard*, an organisation-level resource, and travel with
    `export_org_data`'s own compliance content instead.

    Returns:
        A `(compliance_json, file_assets_by_id)` pair, in the same shape
        `project_export.collect_project_data` itself returns — merged into
        that function's own two return values, not returned as a separate
        top-level bundle section.
    """
    file_assets_by_id: dict[UUID, FileAsset] = {}
    assignments = list(db.scalars(select(ProjectCompliance).where(ProjectCompliance.project_id == project.id)).all())
    evidence_rows = list(db.scalars(select(ComplianceEvidence).where(ComplianceEvidence.project_id == project.id)).all())
    evidence_ref_by_id = {e.id: f"EV-{i + 1}" for i, e in enumerate(evidence_rows)}

    project_compliances_json = []
    for pc in assignments:
        version = db.get(ComplianceStandardVersion, pc.standard_version_id)
        standard = db.get(ComplianceStandard, version.standard_id)
        requirements = list(
            db.scalars(select(ComplianceRequirement).where(ComplianceRequirement.standard_version_id == version.id)).all()
        )
        requirement_by_id = {r.id: r for r in requirements}
        pcrs = list(
            db.scalars(select(ProjectComplianceRequirement).where(ProjectComplianceRequirement.project_compliance_id == pc.id)).all()
        )
        pcr_ids = [pcr.id for pcr in pcrs]

        actions_by_requirement_id: dict[UUID, list[ComplianceRequiredAction]] = {}
        if requirements:
            for a in db.scalars(
                select(ComplianceRequiredAction).where(ComplianceRequiredAction.requirement_id.in_(requirement_by_id))
            ).all():
                actions_by_requirement_id.setdefault(a.requirement_id, []).append(a)
        assessments = list(
            db.scalars(
                select(ComplianceRequiredActionAssessment).where(
                    ComplianceRequiredActionAssessment.project_compliance_requirement_id.in_(pcr_ids)
                )
            ).all()
        ) if pcr_ids else []
        assessments_by_pcr_id: dict[UUID, list[ComplianceRequiredActionAssessment]] = {}
        for a in assessments:
            assessments_by_pcr_id.setdefault(a.project_compliance_requirement_id, []).append(a)
        action_by_id = {a.id: a for actions in actions_by_requirement_id.values() for a in actions}

        req_evidence_links = list(
            db.scalars(
                select(ComplianceEvidenceRequirementLink).where(
                    ComplianceEvidenceRequirementLink.project_compliance_requirement_id.in_(pcr_ids)
                )
            ).all()
        ) if pcr_ids else []
        req_evidence_refs_by_pcr_id: dict[UUID, list[str]] = {}
        for link in req_evidence_links:
            req_evidence_refs_by_pcr_id.setdefault(link.project_compliance_requirement_id, []).append(
                evidence_ref_by_id[link.evidence_id]
            )
        assessment_ids = [a.id for a in assessments]
        action_evidence_links = list(
            db.scalars(
                select(ComplianceEvidenceActionLink).where(
                    ComplianceEvidenceActionLink.required_action_assessment_id.in_(assessment_ids)
                )
            ).all()
        ) if assessment_ids else []
        action_evidence_refs_by_assessment_id: dict[UUID, list[str]] = {}
        for link in action_evidence_links:
            action_evidence_refs_by_assessment_id.setdefault(link.required_action_assessment_id, []).append(
                evidence_ref_by_id[link.evidence_id]
            )

        requirements_json = []
        for pcr in pcrs:
            requirement = requirement_by_id.get(pcr.requirement_id)
            if requirement is None:
                continue
            actions_json = []
            for assessment in assessments_by_pcr_id.get(pcr.id, []):
                action = action_by_id.get(assessment.required_action_id)
                if action is None:
                    continue
                actions_json.append({
                    "required_action_key": _required_action_key(action), "_assignee": assessment.assignee_id,
                    "due_date": _j(assessment.due_date), "is_completed": assessment.is_completed,
                    "completed_at": _j(assessment.completed_at), "_completed_by": assessment.completed_by,
                    "notes": assessment.notes, "evidence_refs": action_evidence_refs_by_assessment_id.get(assessment.id, []),
                })
            requirements_json.append({
                "requirement_key": _requirement_key(requirement),
                "explicit_applicability": pcr.explicit_applicability.value if pcr.explicit_applicability else None,
                "justification": pcr.justification, "notes": pcr.notes, "compliance_status": pcr.compliance_status.value,
                "assessed_at": _j(pcr.assessed_at), "_assessed_by": pcr.assessed_by,
                "applicability_set_at": _j(pcr.applicability_set_at), "_applicability_set_by": pcr.applicability_set_by,
                "approval_state": pcr.approval_state.value, "approval_decided_at": _j(pcr.approval_decided_at),
                "_approval_decided_by": pcr.approval_decided_by, "decision_note": pcr.decision_note,
                "evidence_refs": req_evidence_refs_by_pcr_id.get(pcr.id, []), "required_actions": actions_json,
            })

        reviews_json = []
        for review in db.scalars(select(ComplianceReview).where(ComplianceReview.project_compliance_id == pc.id)).all():
            evidence_refs = [
                evidence_ref_by_id[link.evidence_id]
                for link in db.scalars(select(ComplianceReviewEvidenceLink).where(ComplianceReviewEvidenceLink.review_id == review.id))
                if link.evidence_id in evidence_ref_by_id
            ]
            reviews_json.append({
                "frequency_label": review.frequency_label, "recurrence_days": review.recurrence_days,
                "next_due_date": _j(review.next_due_date), "_owner": review.owner_id, "status": review.status.value,
                "notes": review.notes, "outcome": review.outcome.value if review.outcome else None,
                "completed_at": _j(review.completed_at), "_completed_by": review.completed_by,
                "_created_by": review.created_by, "evidence_refs": evidence_refs,
            })

        project_compliances_json.append({
            "standard_reference": standard.reference, "version_label": version.version_label,
            "assigned_at": _j(pc.assigned_at), "_assigned_by": pc.assigned_by,
            "target_compliance_date": _j(pc.target_compliance_date), "is_archived": pc.is_archived,
            "archived_at": _j(pc.archived_at), "_archived_by": pc.archived_by,
            "requirements": requirements_json, "reviews": reviews_json,
        })

    evidence_json = []
    for e in evidence_rows:
        revalidations = list(
            db.scalars(select(ComplianceEvidenceRevalidation).where(ComplianceEvidenceRevalidation.evidence_id == e.id)).all()
        )
        attachments = []
        for _ef, asset, uploader in db.execute(
            select(ComplianceEvidenceFile, FileAsset, User)
            .join(FileAsset, FileAsset.id == ComplianceEvidenceFile.file_id)
            .join(User, User.id == ComplianceEvidenceFile.linked_by)
            .where(ComplianceEvidenceFile.evidence_id == e.id)
        ).all():
            file_assets_by_id[asset.id] = asset
            attachments.append({
                "file_ref": f"{asset.id}_{asset.filename}", "filename": asset.filename,
                "content_type": asset.content_type, "linked_by_email": uploader.email,
            })
        evidence_json.append({
            "ref": evidence_ref_by_id[e.id], "title": e.title, "description": e.description,
            "issuing_organisation": e.issuing_organisation, "issued_date": _j(e.issued_date),
            "expiry_date": _j(e.expiry_date), "_provided_by": e.provided_by, "provided_at": _j(e.provided_at),
            "notes": e.notes, "is_archived": e.is_archived, "archived_at": _j(e.archived_at),
            "_archived_by": e.archived_by, "attachments": attachments,
            "revalidations": [
                {
                    "_revalidated_by": r.revalidated_by, "revalidated_at": _j(r.revalidated_at),
                    "previous_expiry_date": _j(r.previous_expiry_date), "new_expiry_date": _j(r.new_expiry_date),
                    "justification": r.justification,
                }
                for r in revalidations
            ],
        })

    # One batched, deployment-wide user lookup for every placeholder
    # `_<field>` key collected above, mirroring `project_export.collect_
    # project_data`'s own established "single lookup, not N+1" convention;
    # resolved in a second pass over the already-built structures below
    # rather than threaded through the nested loops above, matching
    # `export_org_data`'s identical two-pass shape for the same reason.
    user_ids: set[UUID | None] = {pc["_assigned_by"] for pc in project_compliances_json} | {
        pc["_archived_by"] for pc in project_compliances_json
    }
    for pc in project_compliances_json:
        for r in pc["requirements"]:
            user_ids |= {r["_assessed_by"], r["_applicability_set_by"], r["_approval_decided_by"]}
            for a in r["required_actions"]:
                user_ids |= {a["_assignee"], a["_completed_by"]}
        for rv in pc["reviews"]:
            user_ids |= {rv["_owner"], rv["_completed_by"], rv["_created_by"]}
    for e in evidence_json:
        user_ids |= {e["_provided_by"], e["_archived_by"]}
        for r in e["revalidations"]:
            user_ids.add(r["_revalidated_by"])
    user_ids.discard(None)
    email_by_id = {u.id: u.email for u in db.scalars(select(User).where(User.id.in_(user_ids)))} if user_ids else {}

    def email(user_id: UUID | None) -> str | None:
        return email_by_id.get(user_id) if user_id else None

    for pc in project_compliances_json:
        pc["assigned_by_email"] = email(pc.pop("_assigned_by"))
        pc["archived_by_email"] = email(pc.pop("_archived_by"))
        for r in pc["requirements"]:
            r["assessed_by_email"] = email(r.pop("_assessed_by"))
            r["applicability_set_by_email"] = email(r.pop("_applicability_set_by"))
            r["approval_decided_by_email"] = email(r.pop("_approval_decided_by"))
            for a in r["required_actions"]:
                a["assignee_email"] = email(a.pop("_assignee"))
                a["completed_by_email"] = email(a.pop("_completed_by"))
        for rv in pc["reviews"]:
            rv["owner_email"] = email(rv.pop("_owner"))
            rv["completed_by_email"] = email(rv.pop("_completed_by"))
            rv["created_by_email"] = email(rv.pop("_created_by"))
    for e in evidence_json:
        e["provided_by_email"] = email(e.pop("_provided_by"))
        e["archived_by_email"] = email(e.pop("_archived_by"))
        for r in e["revalidations"]:
            r["revalidated_by_email"] = email(r.pop("_revalidated_by"))

    return {"compliance_project_compliances": project_compliances_json, "compliance_evidence": evidence_json}, file_assets_by_id


def import_project_data(
    db: Session, project: Project, data: dict[str, Any], file_bytes_by_ref: dict[str, bytes],
    current_user: User, users: UserResolver, warnings: BundleImportWarnings,
) -> None:
    """`ModuleProjectBundleHooks.import_` — reconstructs a project's
    Compliance Module content (§29) from a bundle's `compliance_evidence`/
    `compliance_project_compliances` keys, called from `project_export.
    apply_project_data` after every core requirement/change-request/
    baseline section above it has already run.

    Evidence is created first (independent of any assignment), so its
    export-scoped `ref`s can be resolved while building each assignment's
    requirement/required-action evidence links below. For each assignment,
    the assigned standard/version is looked up in the *target* organisation
    by `(standard_reference, version_label)` — an assignment whose standard
    isn't present there at all is skipped entirely, with a warning (this
    module's own docstring explains why the standard itself is never
    re-embedded/re-created here). Once resolved, a fresh `ProjectCompliance`
    row is created and `service.materialize_assessment_rows` is called to
    build the same default `ProjectComplianceRequirement`/
    `ComplianceRequiredActionAssessment` rows the normal "assign a standard
    to a project" endpoint creates — this function then overlays the
    bundle's recorded assessment state on top of that default scaffold
    (matched per requirement via `_requirement_key`, per required action via
    `_required_action_key`) rather than constructing those rows from scratch
    itself, reusing this module's own established "don't duplicate existing
    infrastructure" precedent one level down.

    A requirement or required action named in the bundle that doesn't match
    anything in the target version (e.g. the standard was independently
    edited between export and import, or a `(reference, name)` collision —
    see `_requirement_key`'s own docstring) is skipped with a warning; its
    default (`NOT_STARTED`/unassessed) state is left as `materialize_
    assessment_rows` created it, never silently fabricated from the bundle.
    """
    organization_id = project.organization_id

    evidence_id_by_ref: dict[str, UUID] = {}
    for e in data.get("compliance_evidence", []):
        evidence = ComplianceEvidence(
            project_id=project.id, title=e["title"], description=e.get("description", ""),
            issuing_organisation=e.get("issuing_organisation"), issued_date=_date(e.get("issued_date")),
            expiry_date=_date(e.get("expiry_date")),
            provided_by=users.resolve(e.get("provided_by_email"), required=True, context=f"Evidence {e['title']!r} provider"),
            provided_at=_dt(e.get("provided_at")) or datetime.now(UTC), notes=e.get("notes", ""),
            is_archived=e.get("is_archived", False), archived_at=_dt(e.get("archived_at")),
            archived_by=users.resolve(e.get("archived_by_email"), required=False, context=f"Evidence {e['title']!r} archiver"),
        )
        db.add(evidence)
        db.flush()
        evidence_id_by_ref[e["ref"]] = evidence.id

        for att in e.get("attachments", []):
            att_bytes = file_bytes_by_ref.get(att["file_ref"])
            if att_bytes is None:
                continue
            uploader_id = (
                users.resolve(att.get("linked_by_email"), required=False, context="Evidence attachment uploader")
                or current_user.id
            )
            asset = import_bundled_file(
                db, organization_id=organization_id, uploaded_by=uploader_id, filename=att["filename"],
                content_type=att.get("content_type") or "application/octet-stream", data=att_bytes,
            )
            db.add(ComplianceEvidenceFile(evidence_id=evidence.id, file_id=asset.id, linked_by=uploader_id, created_at=datetime.now(UTC)))

        for r in e.get("revalidations", []):
            revalidated_at = _dt(r.get("revalidated_at")) or datetime.now(UTC)
            db.add(ComplianceEvidenceRevalidation(
                evidence_id=evidence.id,
                revalidated_by=users.resolve(r.get("revalidated_by_email"), required=True, context=f"Evidence {e['title']!r} revalidation"),
                revalidated_at=revalidated_at, previous_expiry_date=_date(r.get("previous_expiry_date")),
                new_expiry_date=_date(r.get("new_expiry_date")), justification=r.get("justification", ""),
                created_at=revalidated_at,
            ))

    for pc_data in data.get("compliance_project_compliances", []):
        standard_reference, version_label = pc_data["standard_reference"], pc_data["version_label"]
        standard = db.scalar(
            select(ComplianceStandard).where(
                ComplianceStandard.organization_id == organization_id, ComplianceStandard.reference == standard_reference
            )
        )
        version = db.scalar(
            select(ComplianceStandardVersion).where(
                ComplianceStandardVersion.standard_id == standard.id, ComplianceStandardVersion.version_label == version_label
            )
        ) if standard is not None else None
        if standard is None or version is None:
            warnings.add(
                f"Compliance standard {standard_reference!r} v{version_label} does not exist in the target "
                "organisation — this project's assignment to it (and its assessment data) was skipped."
            )
            continue

        project_compliance = ProjectCompliance(
            project_id=project.id, standard_version_id=version.id,
            assigned_at=_dt(pc_data.get("assigned_at")) or datetime.now(UTC),
            assigned_by=users.resolve(
                pc_data.get("assigned_by_email"), required=True, context=f"Assignment to {standard_reference} assigner"
            ),
            target_compliance_date=_date(pc_data.get("target_compliance_date")),
            is_archived=pc_data.get("is_archived", False), archived_at=_dt(pc_data.get("archived_at")),
            archived_by=users.resolve(
                pc_data.get("archived_by_email"), required=False, context=f"Assignment to {standard_reference} archiver"
            ),
        )
        db.add(project_compliance)
        db.flush()
        materialize_assessment_rows(db, project_compliance_id=project_compliance.id, standard_version_id=version.id)
        db.flush()

        requirements = list(
            db.scalars(select(ComplianceRequirement).where(ComplianceRequirement.standard_version_id == version.id)).all()
        )
        requirement_id_by_key: dict[str, UUID] = {}
        for r in requirements:
            requirement_id_by_key.setdefault(_requirement_key(r), r.id)
        pcr_by_requirement_id = {
            pcr.requirement_id: pcr
            for pcr in db.scalars(
                select(ProjectComplianceRequirement).where(ProjectComplianceRequirement.project_compliance_id == project_compliance.id)
            ).all()
        }

        for r_data in pc_data.get("requirements", []):
            requirement_id = requirement_id_by_key.get(r_data["requirement_key"])
            pcr = pcr_by_requirement_id.get(requirement_id) if requirement_id else None
            if pcr is None:
                warnings.add(
                    f"Requirement {r_data['requirement_key']!r} under {standard_reference} v{version_label} was not "
                    "found in the target organisation's standard — its recorded assessment was skipped."
                )
                continue

            pcr.explicit_applicability = (
                ComplianceApplicability(r_data["explicit_applicability"]) if r_data.get("explicit_applicability") else None
            )
            pcr.justification = r_data.get("justification", "")
            pcr.notes = r_data.get("notes", "")
            pcr.compliance_status = ComplianceStatus(r_data.get("compliance_status", "not_started"))
            pcr.assessed_at = _dt(r_data.get("assessed_at"))
            pcr.assessed_by = users.resolve(
                r_data.get("assessed_by_email"), required=False, context=f"Requirement {r_data['requirement_key']} assessor"
            )
            pcr.applicability_set_at = _dt(r_data.get("applicability_set_at"))
            pcr.applicability_set_by = users.resolve(
                r_data.get("applicability_set_by_email"), required=False,
                context=f"Requirement {r_data['requirement_key']} applicability setter",
            )
            pcr.approval_state = ComplianceApprovalState(r_data.get("approval_state", "not_assessed"))
            pcr.approval_decided_at = _dt(r_data.get("approval_decided_at"))
            pcr.approval_decided_by = users.resolve(
                r_data.get("approval_decided_by_email"), required=False,
                context=f"Requirement {r_data['requirement_key']} approval decider",
            )
            pcr.decision_note = r_data.get("decision_note", "")
            for ref in r_data.get("evidence_refs", []):
                evidence_id = evidence_id_by_ref.get(ref)
                if evidence_id is not None:
                    db.add(ComplianceEvidenceRequirementLink(
                        evidence_id=evidence_id, project_compliance_requirement_id=pcr.id,
                        linked_by=current_user.id, created_at=datetime.now(UTC),
                    ))

            actions = list(
                db.scalars(select(ComplianceRequiredAction).where(ComplianceRequiredAction.requirement_id == requirement_id)).all()
            )
            action_id_by_key: dict[str, UUID] = {}
            for a in actions:
                action_id_by_key.setdefault(_required_action_key(a), a.id)
            assessment_by_action_id = {
                assessment.required_action_id: assessment
                for assessment in db.scalars(
                    select(ComplianceRequiredActionAssessment).where(
                        ComplianceRequiredActionAssessment.project_compliance_requirement_id == pcr.id
                    )
                ).all()
            }
            for a_data in r_data.get("required_actions", []):
                action_id = action_id_by_key.get(a_data["required_action_key"])
                assessment = assessment_by_action_id.get(action_id) if action_id else None
                if assessment is None:
                    warnings.add(
                        f"Required action {a_data['required_action_key']!r} under requirement "
                        f"{r_data['requirement_key']!r} was not found — its recorded assessment was skipped."
                    )
                    continue
                assessment.assignee_id = users.resolve(
                    a_data.get("assignee_email"), required=False, context=f"Required action {a_data['required_action_key']} assignee"
                )
                assessment.due_date = _date(a_data.get("due_date"))
                assessment.is_completed = a_data.get("is_completed", False)
                assessment.completed_at = _dt(a_data.get("completed_at"))
                assessment.completed_by = users.resolve(
                    a_data.get("completed_by_email"), required=False,
                    context=f"Required action {a_data['required_action_key']} completer",
                )
                assessment.notes = a_data.get("notes", "")
                for ref in a_data.get("evidence_refs", []):
                    evidence_id = evidence_id_by_ref.get(ref)
                    if evidence_id is not None:
                        db.add(ComplianceEvidenceActionLink(
                            evidence_id=evidence_id, required_action_assessment_id=assessment.id,
                            linked_by=current_user.id, created_at=datetime.now(UTC),
                        ))

        for rv_data in pc_data.get("reviews", []):
            review = ComplianceReview(
                project_compliance_id=project_compliance.id, standard_id=None,
                frequency_label=rv_data.get("frequency_label", ""), recurrence_days=rv_data.get("recurrence_days"),
                next_due_date=_date(rv_data.get("next_due_date")) or date.today(),
                owner_id=users.resolve(rv_data.get("owner_email"), required=False, context="Compliance review owner"),
                status=ComplianceReviewStatus(rv_data.get("status", "scheduled")), notes=rv_data.get("notes", ""),
                outcome=ComplianceReviewOutcome(rv_data["outcome"]) if rv_data.get("outcome") else None,
                completed_at=_dt(rv_data.get("completed_at")),
                completed_by=users.resolve(rv_data.get("completed_by_email"), required=False, context="Compliance review completer"),
                created_by=users.resolve(rv_data.get("created_by_email"), required=True, context="Compliance review creator"),
            )
            db.add(review)
            db.flush()
            for ref in rv_data.get("evidence_refs", []):
                evidence_id = evidence_id_by_ref.get(ref)
                if evidence_id is not None:
                    db.add(ComplianceReviewEvidenceLink(
                        evidence_id=evidence_id, review_id=review.id, linked_by=current_user.id, created_at=datetime.now(UTC)
                    ))
