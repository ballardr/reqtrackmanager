"""
Module: modules.traceability.bundle

Carries governance profiles in the organisation bundle and a project's choices in the project bundle, through
`ModuleOrgBundleHooks` and `ModuleProjectBundleHooks`.

Responsibilities:
- Organisation export: each profile (name, description, mode, target kind) with the policy rows of every registered
  `ProfileContributor`, then, once projects have their portable references, each profile's targets and exemptions by
  project reference.
- Organisation import: create the profiles first (projects import afterwards and name them), then add their targets and
  exemptions when every project exists. A merge keeps the organisation's own profile of the same name and adds only the
  names it lacks.
- Project export and import: the project's own choices, by profile name, its own approval policy rows (roles by kind
  and key, a custom role by name), its own review policy rows (the default owner by email or group name) and its own
  baseline policy (check keys and required field keys).
- Template copy: the choices and approval, review and baseline policy rows are project configuration, copied unchanged to a project made from a
  template.

Design decisions:
- An import never relaxes an Enforced profile: a project bundle carries no exemption (exemptions are organisation
  records), a choice for an Enforced profile is refused, and a merge never changes an existing profile.
- A profile added by a merge arrives in the mode it was exported in; an Enforced one is reported in the import warnings
  because it begins to bind projects of the target organisation.
- The profiles imported by the first phase are remembered on the session (`db.info`) so the second phase writes
  targets only for those, never for a profile the merge kept.
- Policy rows travel with their contributor; one it does not know (a module not installed here) is reported and skipped.

Dependencies: `modules.traceability.profiles` (writes, audit), `modules.registry` (contributors), `services.bundle_common`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules import registry
from app.modules.traceability import approval_policy, baseline_policy, profiles, review_policy
from app.modules.traceability.enums import ProfileMode, ProfileTargetKind
from app.modules.traceability.models import (
    GovernanceProfile,
    GovernanceProfileChoice,
    GovernanceProfileExemption,
    GovernanceProfileTarget,
)
from app.services.bundle_common import BundleImportWarnings, UserResolver

PROFILES_KEY = "governance_profiles"
TARGETS_KEY = "governance_profile_targets"
EXEMPTIONS_KEY = "governance_profile_exemptions"
CHOICES_KEY = "governance_profile_choices"
APPROVAL_POLICIES_KEY = approval_policy.PROJECT_ROWS_KEY
REVIEW_POLICIES_KEY = review_policy.PROJECT_ROWS_KEY
BASELINE_POLICY_KEY = baseline_policy.PROJECT_ROW_KEY
_IMPORTED_INFO_KEY = "governance_profiles_imported"


def _organization_profiles(db: Session, organization_id: uuid.UUID) -> list[GovernanceProfile]:
    return list(db.scalars(
        select(GovernanceProfile).where(GovernanceProfile.organization_id == organization_id).order_by(GovernanceProfile.name)
    ))


def _entry_order(entry: Mapping[str, Any]) -> tuple[str, str]:
    """Sort key of a target or exemption entry, so an export is stable."""
    return (str(entry["profile"]), str(entry["project_ref"]))


def export_org_data(db: Session, org: Organization) -> dict[str, Any]:
    """`ModuleOrgBundleHooks.export`: the organisation's profiles with every contributor's policy rows."""
    contributors = [(f"{module_key}:{c.key}", c) for module_key, c in registry.get_profile_contributors()]
    entries = []
    for profile in _organization_profiles(db, org.id):
        entry: dict[str, Any] = {
            "name": profile.name, "description": profile.description, "mode": profile.mode, "target_kind": profile.target_kind,
        }
        contributions = {key: c.export_rows(db, profile.id) for key, c in contributors}
        entry["contributions"] = {key: rows for key, rows in contributions.items() if rows}
        entries.append(entry)
    return {PROFILES_KEY: entries}


def export_org_project_data(db: Session, org: Organization, project_ref_by_id: Mapping[uuid.UUID, str]) -> dict[str, Any]:
    """`ModuleOrgBundleHooks.export_with_projects`: each profile's targets and exemptions, naming projects by bundle
    reference (a project outside the bundle is left out)."""
    by_id = {p.id: p.name for p in _organization_profiles(db, org.id)}
    targets = [
        {"profile": by_id[t.profile_id], "project_ref": project_ref_by_id[t.project_id], "include_children": t.include_children}
        for t in db.scalars(select(GovernanceProfileTarget).where(GovernanceProfileTarget.profile_id.in_(by_id)))
        if t.project_id in project_ref_by_id
    ] if by_id else []
    exemptions = [
        {
            "profile": by_id[e.profile_id], "project_ref": project_ref_by_id[e.project_id],
            "include_children": e.include_children, "reason": e.reason,
        }
        for e in db.scalars(select(GovernanceProfileExemption).where(GovernanceProfileExemption.profile_id.in_(by_id)))
        if e.project_id in project_ref_by_id
    ] if by_id else []
    return {TARGETS_KEY: sorted(targets, key=_entry_order), EXEMPTIONS_KEY: sorted(exemptions, key=_entry_order)}


def import_org_data(
    db: Session, org: Organization, data: dict[str, Any], users: UserResolver, warnings: BundleImportWarnings,
    resolutions: dict[str, str] | None,
) -> None:
    """`ModuleOrgBundleHooks.import_`: creates the bundle's profiles and their policy rows. A name the organisation
    already has is kept as it is (only a merge can meet one)."""
    contributors = {f"{module_key}:{c.key}": c for module_key, c in registry.get_profile_contributors()}
    imported: dict[str, uuid.UUID] = db.info.setdefault(_IMPORTED_INFO_KEY, {})
    imported.clear()
    for entry in data.get(PROFILES_KEY) or []:
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        if profiles.find_profile_by_name(db, org.id, name) is not None:
            warnings.add(f"The organisation already has a governance profile named {name!r}; it was kept unchanged.")
            continue
        try:
            profile = profiles.create_profile(
                db, organization=org, name=name, description=str(entry.get("description") or ""),
                mode=str(entry.get("mode", "")),
                target_kind=str(entry.get("target_kind", "")), targets=[], actor_id=users.importing_user_id,
            )
        except HTTPException as error:
            warnings.add(f"The governance profile {name!r} was not imported: {error.detail}")
            continue
        imported[name.lower()] = profile.id
        if resolutions is not None and profile.mode == ProfileMode.ENFORCED.value:
            warnings.add(f"The governance profile {name!r} is Enforced and now binds the projects it reaches in this organisation.")
        for key, rows in (entry.get("contributions") or {}).items():
            contributor = contributors.get(key)
            if contributor is None:
                warnings.add(f"The {key!r} policy of the governance profile {name!r} was not imported: it is not available here.")
                continue
            contributor.import_rows(db, profile.id, rows, warnings.add)


def import_org_project_data(
    db: Session, org: Organization, data: dict[str, Any], project_id_by_ref: Mapping[str, uuid.UUID], users: UserResolver,
    warnings: BundleImportWarnings, resolutions: dict[str, str] | None,
) -> None:
    """`ModuleOrgBundleHooks.import_with_projects`: writes the targets and exemptions of the profiles `import_org_data`
    created, once every project of the bundle exists. An entry naming a project that was not imported is skipped."""
    imported: dict[str, uuid.UUID] = db.info.pop(_IMPORTED_INFO_KEY, {})
    if not imported:
        return
    specs: dict[uuid.UUID, list[profiles.TargetSpec]] = {pid: [] for pid in imported.values()}
    for entry in data.get(TARGETS_KEY) or []:
        profile_id = imported.get(str(entry.get("profile", "")).lower())
        project_id = project_id_by_ref.get(str(entry.get("project_ref", "")))
        if profile_id is not None and project_id is not None:
            specs[profile_id].append(profiles.TargetSpec(project_id=project_id, include_children=bool(entry.get("include_children"))))
    for profile_id, targets in specs.items():
        profile = db.get(GovernanceProfile, profile_id)
        if profile is not None and profile.target_kind == ProfileTargetKind.SELECTED_PROJECTS.value and targets:
            profiles.set_targets(
                db, profile=profile, target_kind=profile.target_kind, targets=targets, actor_id=users.importing_user_id,
            )
    for entry in data.get(EXEMPTIONS_KEY) or []:
        profile_id = imported.get(str(entry.get("profile", "")).lower())
        project_id = project_id_by_ref.get(str(entry.get("project_ref", "")))
        profile = None if profile_id is None else db.get(GovernanceProfile, profile_id)
        if profile is None or project_id is None:
            continue
        try:
            profiles.add_exemption(
                db, profile=profile, project_id=project_id, include_children=bool(entry.get("include_children")),
                reason=str(entry.get("reason") or ""), actor_id=users.importing_user_id,
            )
        except HTTPException as error:
            warnings.add(f"An exemption from the governance profile {profile.name!r} was not imported: {error.detail}")


def export_project_data(db: Session, project: Project) -> tuple[dict[str, Any], dict[uuid.UUID, Any]]:
    """`ModuleProjectBundleHooks.export`: the project's own choices, by profile name."""
    rows = db.execute(
        select(GovernanceProfile.name, GovernanceProfileChoice.opted_in)
        .join(GovernanceProfileChoice, GovernanceProfileChoice.profile_id == GovernanceProfile.id)
        .where(GovernanceProfileChoice.project_id == project.id)
        .order_by(GovernanceProfile.name)
    ).tuples().all()
    return {
        CHOICES_KEY: [{"profile": name, "opted_in": opted_in} for name, opted_in in rows],
        APPROVAL_POLICIES_KEY: approval_policy.export_project_rows(db, project),
        REVIEW_POLICIES_KEY: review_policy.export_project_rows(db, project),
        BASELINE_POLICY_KEY: baseline_policy.export_project_row(db, project),
    }, {}


def import_project_data(
    db: Session, project: Project, data: dict[str, Any], file_bytes: dict[str, bytes], current_user: User,
    users: UserResolver, warnings: BundleImportWarnings,
) -> None:
    """`ModuleProjectBundleHooks.import_`: records the bundle's choices against the organisation's profiles of the same
    name. A name the organisation lacks, an Enforced profile and a choice the profile's mode does not take are reported
    and skipped, so an import never relaxes what the organisation enforces. The project's own approval policy rows are
    written as exported; they only add approvers, so no organisation policy is relaxed. The review policy rows likewise only
    tighten (the shortest interval and longest lead apply). The baseline policy only adds checks and required fields."""
    approval_policy.import_project_rows(db, project, data.get(APPROVAL_POLICIES_KEY) or [], warnings.add)
    review_policy.import_project_rows(db, project, data.get(REVIEW_POLICIES_KEY) or [], warnings.add)
    baseline_policy.import_project_row(db, project, data.get(BASELINE_POLICY_KEY), warnings.add)
    for entry in data.get(CHOICES_KEY) or []:
        name = str(entry.get("profile", ""))
        profile = profiles.find_profile_by_name(db, project.organization_id, name)
        if profile is None:
            warnings.add(f"The governance profile {name!r} does not exist in this organisation; the project's choice was not imported.")
            continue
        try:
            profiles.set_choice(
                db, profile=profile, project=project, opted_in=bool(entry.get("opted_in")), actor_id=current_user.id,
                require_reach=False,
            )
        except HTTPException as error:
            warnings.add(f"The project's choice about the governance profile {name!r} was not imported: {error.detail}")
