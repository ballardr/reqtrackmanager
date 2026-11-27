"""
Module: modules.traceability.baseline_policy

The baseline policy of governance: which checks run before a project's baselines and which fields a record must have
filled, set by a governance profile or by a project. Registered as the `baseline_policies` part's policy resolver, profile
contributor and project bundle entry.

Responsibilities:
- Write a profile's or a project's policy (`set_profile_settings`, `set_project_settings`), validating the checks, the
  record types and the field keys and recording one audit event each (check keys and field keys, never record content).
- Answer the core `GovernanceSeam.BASELINE` for a project (`resolve_project_policy`) and give the required-fields check its
  configuration (`required_fields`).
- Describe a profile's policy and a project's effective policy with where each check and field came from
  (`profile_policy`, `project_policy`), for the screens.
- Count, export and import a profile's row (`count_rows`, `export_rows`, `import_rows`) and a project's own row
  (`export_project_row`, `import_project_row`).

Design decisions:
- A baseline is a whole-project act, so a policy is one row per owner (a profile or a project) with its enabled check keys
  and its required fields as child rows, not one row per record type.
- A policy only tightens: the checks and fields of every source are merged by union, so a profile, a project and an
  ancestor can each ask for more and none can take away what another asked. Each source's checks keep the baseline kinds
  and approvals that source chose (`applies_to_stage`, `applies_to_manual`, `approval_checks`), so a profile's stage
  check never starts to run before a manual baseline because a project asked for another check there.
- A stage baseline is checked by the stage setting however the stage was moved; the automated approval setting adds the
  review deadline's approval for a source that checks no other stage baseline, and never removes the stage setting.
- Which profiles apply is `profile_resolution`'s decision; this file reads their row. An exempt or opted-out project
  therefore does not get a profile's checks.
- A project's own row beats the nearest ancestor's, so a child project can follow its parent (no row) or set its own. A row
  with no checks and no fields is a deliberate "no checks here" and stops the ancestor's applying.
- A required field is the key of one of the type's list columns (`RecordColumn.key`), so every type a baseline can hold is
  covered with no per-type code and a project's custom fields are included. A profile cannot see a project's custom
  fields, so it accepts any key and a project's own row accepts only the keys its columns have. A stored key the project's
  type has no column for is skipped when the check runs.
- Telling managers of a refused automatic approval is one flag per policy, merged like the checks: it is on when any applying
  policy that holds a check or a field asks for it, so an enforced profile's notice cannot be switched off by a project.
- A check key whose provider is not registered or not in effect for the project is kept and runs nothing.
- Import writes a project's row without an audit event: the import itself is the recorded act.

Dependencies: `modules.registry` (check providers, snapshot providers, record tables), `profile_resolution`,
`services.project_hierarchy`, `services.governance_seams`, `models`, `services.audit`.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.modules import registry
from app.modules.seams import BaselinePolicy
from app.modules.traceability.enums import ApprovalCheckMode
from app.modules.traceability.models import (
    GovernanceBaselineCheck,
    GovernanceBaselinePolicy,
    GovernanceBaselineRequiredField,
    GovernanceProfile,
)
from app.modules.traceability.profile_resolution import applicable_profiles
from app.services import governance_seams, lifecycles
from app.services.audit import log_event
from app.services.baseline import REQUIREMENT_ITEM_TYPE
from app.services.project_hierarchy import get_project_chain_ids

PROFILE_AUDIT_ENTITY_TYPE = "governance_profile"
PROJECT_AUDIT_ENTITY_TYPE = "governance_baseline_policy"
KIND_BASELINE = "baseline"
PROJECT_ROW_KEY = "governance_baseline_policy"
FIELD_KEY_MAX_LENGTH = 100

BaselineKindName = Literal["stage", "manual", "approval"]
#: The column kinds that can be blank, so a required field makes sense for them (a flag is never blank and an instant is
#: set by the system).
_FILLABLE_KINDS = frozenset({"text", "enum", "principal", "date", "number", "list"})


@dataclass(frozen=True, order=True)
class RequiredField:
    """One field a record of a type must have filled.

    Attributes:
        artefact_type: The registered record type.
        field_key: The key of one of the type's list columns.
    """

    artefact_type: str
    field_key: str


@dataclass(frozen=True)
class BaselineSettings:
    """What one owner (a profile or a project) asks of baselines.

    Attributes:
        applies_to_stage: Whether the checks run before a stage baseline.
        applies_to_manual: Whether the checks run before a manual baseline.
        approval_checks: Which approvals the checks also run before.
        checks: The enabled namespaced check keys, sorted.
        required_fields: The fields the required-fields check demands, sorted.
        notify_managers: Whether the project's managers are told when a check refuses the automatic approval of a stage.
    """

    applies_to_stage: bool = True
    applies_to_manual: bool = False
    checks: tuple[str, ...] = ()
    required_fields: tuple[RequiredField, ...] = ()
    notify_managers: bool = True
    approval_checks: ApprovalCheckMode = ApprovalCheckMode.OFF

    @property
    def is_empty(self) -> bool:
        """Whether the policy enables no check and names no field."""
        return not self.checks and not self.required_fields

    def applies_to(self, kind: BaselineKindName, *, automated: bool = False) -> bool:
        """Whether the checks run before a baseline of `kind` or a person's approval (`approval`); `automated` marks a stage
        baseline taken by the review deadline."""
        if kind == "approval":
            return self.approval_checks.manual
        if kind == "manual":
            return self.applies_to_manual
        return self.applies_to_stage or (automated and self.approval_checks.automated)

    @property
    def kinds(self) -> set[str]:
        """The names of what the checks run before: `stage`, `manual`, `manual_approval`, `automated_approval`."""
        chosen = (
            ("stage", self.applies_to_stage), ("manual", self.applies_to_manual),
            ("manual_approval", self.approval_checks.manual), ("automated_approval", self.approval_checks.automated),
        )
        return {name for name, on in chosen if on}

    def normalised(self) -> BaselineSettings:
        """The settings with checks and fields de-duplicated and sorted."""
        return BaselineSettings(
            self.applies_to_stage, self.applies_to_manual, tuple(sorted(set(self.checks))),
            tuple(sorted(set(self.required_fields))), self.notify_managers, self.approval_checks,
        )


@dataclass(frozen=True)
class CheckOption:
    """A baseline check an organisation can enable.

    Attributes:
        key: The namespaced key (`<module key>:<check key>`).
        name: Display name.
        module_key: The module that registered it.
        artefact_types: The types it inspects; empty for every type the baseline holds.
    """

    key: str
    name: str
    module_key: str
    artefact_types: tuple[str, ...]


@dataclass(frozen=True)
class BaselineType:
    """A record type a baseline can hold.

    Attributes:
        artefact_type: The registered record type.
        label: Its singular display name.
        module_key: The module that owns it, `""` for a core type.
    """

    artefact_type: str
    label: str
    module_key: str


@dataclass(frozen=True)
class FieldOption:
    """A field of a record type that can be required.

    Attributes:
        key: The list column's key.
        label: The column's display name.
    """

    key: str
    label: str


@dataclass(frozen=True)
class EffectiveCheck:
    """One check that applies to a project, with where it came from.

    Attributes:
        key: The namespaced check key.
        name: Display name, `None` when no provider is registered under the key.
        available: Whether the check is registered and in effect for the project, so it runs.
        stage: Whether it runs before a stage baseline.
        manual: Whether it runs before a manual baseline.
        manual_approval: Whether it runs when a person approves a record.
        automated_approval: Whether it runs when the review deadline approves a stage.
        sources: Profile names, then `"project"` or `"parent_project"`, that enable it.
    """

    key: str
    name: str | None
    available: bool
    stage: bool
    manual: bool
    sources: tuple[str, ...]
    manual_approval: bool = False
    automated_approval: bool = False


@dataclass(frozen=True)
class EffectiveField:
    """One required field that applies to a project, with where it came from.

    Attributes:
        field: The record type and column key.
        stage: Whether it is demanded before a stage baseline.
        manual: Whether it is demanded before a manual baseline.
        manual_approval: Whether it is demanded when a person approves a record.
        automated_approval: Whether it is demanded when the review deadline approves a stage.
        sources: Profile names, then `"project"` or `"parent_project"`, that name it.
    """

    field: RequiredField
    stage: bool
    manual: bool
    sources: tuple[str, ...]
    manual_approval: bool = False
    automated_approval: bool = False


@dataclass(frozen=True)
class ProjectBaselinePolicy:
    """A project's baseline policy.

    Attributes:
        own: The project's own settings, `None` when it has no row (it follows the nearest ancestor's).
        inherited_from: Name of the ancestor project whose row applies, `None` when the project has its own row or no
            ancestor has one.
        checks: Every check that applies, with its sources.
        required_fields: Every required field that applies, with its sources.
        notify_managers: Whether the managers are told of a refused automatic approval (any applying source asks for it).
    """

    own: BaselineSettings | None
    inherited_from: str | None
    checks: list[EffectiveCheck]
    required_fields: list[EffectiveField]
    notify_managers: bool = True


# --- vocabulary -----------------------------------------------------------------------------------


def check_options(db: Session, organization_id: uuid.UUID) -> list[CheckOption]:
    """The baseline checks the organisation can enable: those whose module, and sub-component when it names one, are in
    effect for the organisation, in registry order."""
    options = []
    for module_key, provider in registry.get_baseline_check_providers():
        if not registry.is_module_enabled(db, organization_id, module_key):
            continue
        if provider.sub_component is not None and not registry.is_org_module_subcomponent_enabled(
            db, organization_id, module_key, provider.sub_component,
        ):
            continue
        options.append(CheckOption(f"{module_key}:{provider.key}", provider.name, module_key, provider.artefact_types))
    return options


def baseline_types(db: Session, organization_id: uuid.UUID) -> list[BaselineType]:
    """The record types a baseline can hold that are in effect for the organisation: the requirement and every type a
    module captures through a snapshot provider, in type-name order."""
    found = [BaselineType(REQUIREMENT_ITEM_TYPE, registry.get_artefact_type_label(REQUIREMENT_ITEM_TYPE), "")]
    found.extend(
        BaselineType(artefact_type, registry.get_artefact_type_label(artefact_type), module_key)
        for artefact_type, (module_key, _) in sorted(registry.get_baseline_snapshot_providers().items())
        if lifecycles.enabled_for_organization(db, organization_id, artefact_type, module_key)
    )
    return found


def field_options(db: Session, project: Project) -> dict[str, list[FieldOption]]:
    """The fields of each baseline type that a project can require, in column order: the type's list columns that can be
    blank, including the project's custom fields. A type with no record table or no fillable column is absent."""
    providers = registry.get_record_table_providers()
    options: dict[str, list[FieldOption]] = {}
    for baseline_type in baseline_types(db, project.organization_id):
        provider = providers.get(baseline_type.artefact_type)
        if provider is None:
            continue
        columns = [FieldOption(c.key, c.label) for c in provider.columns(db, project) if c.kind in _FILLABLE_KINDS]
        if columns:
            options[baseline_type.artefact_type] = columns
    return options


# --- writing --------------------------------------------------------------------------------------


def _validated(
    db: Session, settings: BaselineSettings, *, organization_id: uuid.UUID, project: Project | None,
) -> BaselineSettings:
    """`settings` normalised, after checking the baseline kinds, the checks, the types and the field keys.

    Raises:
        HTTPException: 422 when no baseline kind and no approval is chosen, a check is not available to the organisation, a type is
            not one a baseline can hold, a field key is empty or too long, or (for a project) a field is not a column of
            the type.
    """
    if not settings.kinds:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose at least one kind of baseline or approval for the checks.")
    offered = {o.key for o in check_options(db, organization_id)}
    for key in settings.checks:
        if key not in offered:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A baseline check named is not available to this organisation.")
    types = {t.artefact_type for t in baseline_types(db, organization_id)}
    columns = field_options(db, project) if project is not None else {}
    for required in settings.required_fields:
        if required.artefact_type not in types:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A required field names a record type that a baseline cannot hold.")
        if not required.field_key.strip() or len(required.field_key) > FIELD_KEY_MAX_LENGTH:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A required field key must be 1 to 100 characters.")
        if project is not None and required.field_key not in {o.key for o in columns.get(required.artefact_type, [])}:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "A required field is not a field of its record type in this project.",
            )
    return settings.normalised()


def _find(db: Session, profile_id: uuid.UUID | None, project_id: uuid.UUID | None) -> GovernanceBaselinePolicy | None:
    return db.scalar(select(GovernanceBaselinePolicy).where(
        GovernanceBaselinePolicy.profile_id == profile_id if profile_id is not None
        else GovernanceBaselinePolicy.project_id == project_id
    ))


def _write(
    db: Session, *, profile_id: uuid.UUID | None, project_id: uuid.UUID | None, settings: BaselineSettings | None,
) -> bool:
    """Makes the owner's policy row hold exactly `settings` (`None` removes the row; flushed, not audited).

    Returns:
        Whether the stored policy changed.
    """
    policy = _find(db, profile_id, project_id)
    if settings is None:
        if policy is None:
            return False
        db.delete(policy)
        db.flush()
        return True
    created = policy is None
    changed = created
    if policy is None:
        policy = GovernanceBaselinePolicy(
            profile_id=profile_id, project_id=project_id, applies_to_stage=settings.applies_to_stage,
            applies_to_manual=settings.applies_to_manual, notify_managers=settings.notify_managers,
            approval_checks=settings.approval_checks.value,
        )
        db.add(policy)
        db.flush()
    elif (policy.applies_to_stage, policy.applies_to_manual, policy.notify_managers, policy.approval_checks) != (
        settings.applies_to_stage, settings.applies_to_manual, settings.notify_managers, settings.approval_checks.value,
    ):
        policy.applies_to_stage, policy.applies_to_manual = settings.applies_to_stage, settings.applies_to_manual
        policy.notify_managers = settings.notify_managers
        policy.approval_checks = settings.approval_checks.value
        changed = True
    checks = {r.check_key: r for r in db.scalars(select(GovernanceBaselineCheck).where(GovernanceBaselineCheck.policy_id == policy.id))}
    for key, row in checks.items():
        if key not in settings.checks:
            db.delete(row)
            changed = True
    for key in settings.checks:
        if key not in checks:
            db.add(GovernanceBaselineCheck(policy_id=policy.id, check_key=key))
            changed = True
    fields = {
        RequiredField(r.artefact_type, r.field_key): r
        for r in db.scalars(select(GovernanceBaselineRequiredField).where(GovernanceBaselineRequiredField.policy_id == policy.id))
    }
    for field, field_row in fields.items():
        if field not in settings.required_fields:
            db.delete(field_row)
            changed = True
    for field in settings.required_fields:
        if field not in fields:
            db.add(GovernanceBaselineRequiredField(policy_id=policy.id, artefact_type=field.artefact_type, field_key=field.field_key))
            changed = True
    db.flush()
    return changed


def _detail(settings: BaselineSettings | None) -> dict[str, Any]:
    """Audit detail: the baseline kinds, the check keys and the required field keys by type (never record content)."""
    if settings is None:
        return {"settings": None}
    by_type: dict[str, list[str]] = defaultdict(list)
    for field in settings.required_fields:
        by_type[field.artefact_type].append(field.field_key)
    return {
        "applies_to_stage": settings.applies_to_stage, "applies_to_manual": settings.applies_to_manual,
        "approval_checks": settings.approval_checks.value,
        "notify_managers": settings.notify_managers, "checks": list(settings.checks), "required_fields": dict(by_type),
    }


def set_profile_settings(
    db: Session, *, profile: GovernanceProfile, settings: BaselineSettings, actor_id: uuid.UUID,
) -> None:
    """Sets the baseline policy a profile gives.

    Args:
        db: Active session (not committed).
        profile: The profile.
        settings: The policy; one that enables no check and names no field removes the profile's policy.
        actor_id: The acting user.

    Raises:
        HTTPException: 422 for a baseline kind, check, type or field key the organisation cannot use.
    """
    valid = _validated(db, settings, organization_id=profile.organization_id, project=None)
    _write(db, profile_id=profile.id, project_id=None, settings=None if valid.is_empty else valid)
    log_event(
        db, entity_type=PROFILE_AUDIT_ENTITY_TYPE, entity_id=profile.id, action="baseline_updated", actor_id=actor_id,
        organization_id=profile.organization_id, detail=_detail(valid),
    )


def set_project_settings(
    db: Session, *, project: Project, settings: BaselineSettings | None, actor_id: uuid.UUID,
) -> None:
    """Sets the baseline policy a project gives itself.

    Args:
        db: Active session (not committed).
        project: The project.
        settings: The policy; one that enables no check is a choice of no baseline checks that stops the nearest ancestor's
            applying; `None` removes the row so the project follows the nearest ancestor's.
        actor_id: The acting user.

    Raises:
        HTTPException: 422 for a baseline kind, check, type or field the project's organisation cannot use.
    """
    valid = None if settings is None else _validated(db, settings, organization_id=project.organization_id, project=project)
    _write(db, profile_id=None, project_id=project.id, settings=valid)
    log_event(
        db, entity_type=PROJECT_AUDIT_ENTITY_TYPE, entity_id=project.id, action="updated", actor_id=actor_id,
        organization_id=project.organization_id, project_id=project.id, detail=_detail(valid),
    )


# --- reading --------------------------------------------------------------------------------------


def _settings_by_policy(db: Session, policies: Sequence[GovernanceBaselinePolicy]) -> dict[uuid.UUID, BaselineSettings]:
    """The settings of each policy row, with its checks and fields, in three reads."""
    ids = [p.id for p in policies]
    checks: dict[uuid.UUID, list[str]] = defaultdict(list)
    fields: dict[uuid.UUID, list[RequiredField]] = defaultdict(list)
    if ids:
        for policy_id, key in db.execute(
            select(GovernanceBaselineCheck.policy_id, GovernanceBaselineCheck.check_key).where(GovernanceBaselineCheck.policy_id.in_(ids))
        ).tuples():
            checks[policy_id].append(key)
        for policy_id, artefact_type, field_key in db.execute(
            select(
                GovernanceBaselineRequiredField.policy_id, GovernanceBaselineRequiredField.artefact_type,
                GovernanceBaselineRequiredField.field_key,
            ).where(GovernanceBaselineRequiredField.policy_id.in_(ids))
        ).tuples():
            fields[policy_id].append(RequiredField(artefact_type, field_key))
    return {
        p.id: BaselineSettings(
            p.applies_to_stage, p.applies_to_manual, tuple(checks[p.id]), tuple(fields[p.id]), p.notify_managers,
            ApprovalCheckMode(p.approval_checks),
        ).normalised()
        for p in policies
    }


def _sources(
    db: Session, project_id: uuid.UUID, chain: Sequence[uuid.UUID],
) -> tuple[list[tuple[str, BaselineSettings]], BaselineSettings | None, uuid.UUID | None]:
    """The policies that apply to the project in precedence order, as `(source name, settings)`: the applicable profiles,
    then the project's own row or, when it has none, the nearest ancestor's. Also the project's own settings and the
    ancestor whose row applies. `chain` is the project's chain, nearest first, starting with the project itself."""
    applied = applicable_profiles(db, project_id)
    owner_filters = []
    if applied:
        owner_filters.append(GovernanceBaselinePolicy.profile_id.in_([a.profile_id for a in applied]))
    if chain:
        owner_filters.append(GovernanceBaselinePolicy.project_id.in_(chain))
    if not owner_filters:
        return [], None, None
    policies = list(db.scalars(select(GovernanceBaselinePolicy).where(or_(*owner_filters))))
    settings = _settings_by_policy(db, policies)
    by_profile = {p.profile_id: settings[p.id] for p in policies if p.profile_id is not None}
    by_project = {p.project_id: settings[p.id] for p in policies if p.project_id is not None}
    sources: list[tuple[str, BaselineSettings]] = [(a.name, by_profile[a.profile_id]) for a in applied if a.profile_id in by_profile]
    own: BaselineSettings | None = None
    ancestor: uuid.UUID | None = None
    for depth, owner in enumerate(chain):
        if owner in by_project:
            if depth == 0:
                own = by_project[owner]
            else:
                ancestor = owner
            sources.append(("project" if depth == 0 else "parent_project", by_project[owner]))
            break
    return sources, own, ancestor


def resolve_project_policy(db: Session, project_id: uuid.UUID) -> BaselinePolicy | None:
    """`PolicyResolver.resolve_project` for `GovernanceSeam.BASELINE`: the checks that run before each baseline kind and
    approval.

    Args:
        db: Active session (read only).
        project_id: The project.

    Returns:
        The union of the checks of the profiles that apply and of the project's own row (else the nearest ancestor's), each
        with the baselines and approvals its source chose, and whether any source asks for managers to be notified of a
        refused automatic approval; `None` when there are no checks, so no check runs.
    """
    sources, _, _ = _sources(db, project_id, get_project_chain_ids(db, project_id))
    by_kind: dict[str, set[str]] = defaultdict(set)
    for _, settings in sources:
        for kind in settings.kinds:
            by_kind[kind] |= set(settings.checks)
    if not any(by_kind.values()):
        return None

    def keys(kind: str) -> tuple[str, ...]:
        return tuple(sorted(by_kind[kind]))

    return BaselinePolicy(
        stage_checks=keys("stage"), manual_checks=keys("manual"), manual_approval_checks=keys("manual_approval"),
        automated_approval_checks=keys("automated_approval"), notify_managers=_notifies(sources),
    )


def _notifies(sources: Sequence[tuple[str, BaselineSettings]]) -> bool:
    """Whether managers are told of a refused automatic approval: any applying source that holds a check or a field asks
    for it, so no source switches off what another asked for (as with the checks themselves); true when no source holds one."""
    holders = [s for _, s in sources if not s.is_empty]
    return any(s.notify_managers for s in holders) if holders else True


def required_fields(
    db: Session, project_id: uuid.UUID, kind: BaselineKindName, *, automated: bool = False,
) -> dict[str, tuple[str, ...]]:
    """The fields the required-fields check demands before a baseline of `kind` or an approval (`approval`).

    Args:
        db: Active session (read only).
        project_id: The project.
        kind: `stage`, `manual` or `approval`.
        automated: A stage baseline taken by the review deadline.

    Returns:
        `{record type: field keys}`: the union over every source that applies to `kind`; empty when none names a field.
    """
    sources, _, _ = _sources(db, project_id, get_project_chain_ids(db, project_id))
    found: dict[str, set[str]] = defaultdict(set)
    for _, settings in sources:
        if settings.applies_to(kind, automated=automated):
            for field in settings.required_fields:
                found[field.artefact_type].add(field.field_key)
    return {t: tuple(sorted(keys)) for t, keys in found.items()}


def profile_policy(db: Session, profile: GovernanceProfile) -> BaselineSettings:
    """The profile's baseline policy; the defaults (stage baselines, no check) when it has none."""
    policy = _find(db, profile.id, None)
    return BaselineSettings() if policy is None else _settings_by_policy(db, [policy])[policy.id]


def project_policy(db: Session, project: Project) -> ProjectBaselinePolicy:
    """A project's baseline policy: its own row, the ancestor's it follows, and every check and required field that
    applies with where it came from.

    Args:
        db: Active session (read only).
        project: The project.

    Returns:
        The policy; each check says whether it runs (`available`) and each entry names its sources.
    """
    chain = get_project_chain_ids(db, project.id)
    sources, own, ancestor = _sources(db, project.id, chain)
    names = {key: provider.name for key, provider in ((f"{m}:{p.key}", p) for m, p in registry.get_baseline_check_providers())}
    running = {key for key, _ in governance_seams.baseline_checks_for_project(db, project.id)}
    check_sources: dict[str, list[str]] = defaultdict(list)
    check_kinds: dict[str, set[str]] = defaultdict(set)
    field_sources: dict[RequiredField, list[str]] = defaultdict(list)
    field_kinds: dict[RequiredField, set[str]] = defaultdict(set)
    for source, settings in sources:
        kinds = settings.kinds
        for key in settings.checks:
            check_sources[key].append(source)
            check_kinds[key] |= kinds
        for field in settings.required_fields:
            field_sources[field].append(source)
            field_kinds[field] |= kinds
    return ProjectBaselinePolicy(
        notify_managers=_notifies(sources),
        own=own,
        inherited_from=None if ancestor is None else _project_names(db, [ancestor]).get(ancestor),
        checks=[
            EffectiveCheck(
                key, names.get(key), key in running, "stage" in check_kinds[key], "manual" in check_kinds[key],
                tuple(check_sources[key]), "manual_approval" in check_kinds[key], "automated_approval" in check_kinds[key],
            )
            for key in sorted(check_sources)
        ],
        required_fields=[
            EffectiveField(
                f, "stage" in field_kinds[f], "manual" in field_kinds[f], tuple(field_sources[f]),
                "manual_approval" in field_kinds[f], "automated_approval" in field_kinds[f],
            )
            for f in sorted(field_sources)
        ],
    )


def _project_names(db: Session, project_ids: Sequence[uuid.UUID]) -> Mapping[uuid.UUID, str]:
    """The names of the given projects in one read."""
    if not project_ids:
        return {}
    return dict(db.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids))).tuples().all())


# --- the profile contributor ---------------------------------------------------------------------


def count_rows(db: Session, profile_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    """`ProfileContributor.count_rows`: per profile, the checks it enables (a profile with a policy and no check counts
    its required fields, so a policy is never counted as nothing)."""
    policies = list(db.scalars(select(GovernanceBaselinePolicy).where(GovernanceBaselinePolicy.profile_id.in_(profile_ids))))
    settings = _settings_by_policy(db, policies)
    return {
        p.profile_id: max(len(settings[p.id].checks), 1 if settings[p.id].required_fields else 0)
        for p in policies if p.profile_id is not None and not settings[p.id].is_empty
    }


def _entry(settings: BaselineSettings) -> dict[str, Any]:
    """The settings as a bundle entry: required fields grouped by type."""
    by_type: dict[str, list[str]] = defaultdict(list)
    for field in settings.required_fields:
        by_type[field.artefact_type].append(field.field_key)
    return {
        "applies_to_stage": settings.applies_to_stage, "applies_to_manual": settings.applies_to_manual,
        "approval_checks": settings.approval_checks.value,
        "notify_managers": settings.notify_managers, "checks": list(settings.checks),
        "required_fields": [{"artefact_type": t, "fields": keys} for t, keys in sorted(by_type.items())],
    }


def export_rows(db: Session, profile_id: uuid.UUID) -> list[dict[str, Any]]:
    """`ProfileContributor.export_rows`: one `baseline` entry when the profile has a policy, else none."""
    policy = _find(db, profile_id, None)
    if policy is None:
        return []
    return [{"kind": KIND_BASELINE, **_entry(_settings_by_policy(db, [policy])[policy.id])}]


def _import_settings(
    db: Session, entry: Mapping[str, Any], *, project: Project | None, warn: Callable[[str], None],
) -> BaselineSettings:
    """The bundle entry's settings resolved here. A check no installed module registers, a type a baseline cannot hold and
    (for a project) a field the type has no column for are reported through `warn` and left out; a policy that names
    no baseline kind and no approval takes the default (stage baselines). A check or type of a module that is installed but not yet
    switched on for the organisation is kept, as stored data is whenever its module is off.
    """
    registered = {f"{module_key}:{provider.key}" for module_key, provider in registry.get_baseline_check_providers()}
    checks = []
    for key in entry.get("checks") or []:
        if str(key) in registered:
            checks.append(str(key))
        else:
            warn(f"The baseline check {str(key)!r} was not imported: no installed module provides it.")
    types = {REQUIREMENT_ITEM_TYPE, *registry.get_baseline_snapshot_providers()}
    columns = field_options(db, project) if project is not None else {}
    fields: list[RequiredField] = []
    for group in entry.get("required_fields") or []:
        artefact_type = str(group.get("artefact_type", ""))
        if artefact_type not in types:
            warn(f"The required fields for {artefact_type or 'an unnamed type'} were not imported: a baseline cannot hold the type here.")
            continue
        known = {o.key for o in columns.get(artefact_type, [])}
        for key in group.get("fields") or []:
            text = str(key)
            if not text.strip() or len(text) > FIELD_KEY_MAX_LENGTH or (project is not None and text not in known):
                warn(f"The required field {text[:FIELD_KEY_MAX_LENGTH]!r} of {artefact_type} was not imported: the type has no such field here.")
            else:
                fields.append(RequiredField(artefact_type, text))
    stage, manual = bool(entry.get("applies_to_stage", True)), bool(entry.get("applies_to_manual", False))
    approvals = str(entry.get("approval_checks") or ApprovalCheckMode.OFF.value)
    if approvals not in {m.value for m in ApprovalCheckMode}:
        warn(f"The approval check setting {approvals[:40]!r} is not recognised; approvals are not checked by this policy.")
        approvals = ApprovalCheckMode.OFF.value
    if not (stage or manual or approvals != ApprovalCheckMode.OFF.value):
        stage = True
    return BaselineSettings(
        stage, manual, tuple(checks), tuple(fields), bool(entry.get("notify_managers", True)), ApprovalCheckMode(approvals),
    ).normalised()


def import_rows(db: Session, profile_id: uuid.UUID, rows: Sequence[dict[str, Any]], warn: Callable[[str], None]) -> None:
    """`ProfileContributor.import_rows`: writes the bundle's `baseline` entry into the profile. A check or type that is not
    available here and an unknown entry are reported through `warn` and skipped."""
    profile = db.get(GovernanceProfile, profile_id)
    if profile is None:
        return
    for entry in rows:
        if entry.get("kind") != KIND_BASELINE:
            warn("A baseline policy entry of an unknown kind was not imported.")
            continue
        settings = _import_settings(db, entry, project=None, warn=warn)
        if not settings.is_empty:
            _write(db, profile_id=profile_id, project_id=None, settings=settings)


# --- a project's own row in its bundle -----------------------------------------------------------


def export_project_row(db: Session, project: Project) -> dict[str, Any] | None:
    """The project's own policy as a bundle entry, `None` when it has no row (an entry with no checks is a kept choice)."""
    policy = _find(db, None, project.id)
    return None if policy is None else _entry(_settings_by_policy(db, [policy])[policy.id])


def import_project_row(db: Session, project: Project, entry: Mapping[str, Any] | None, warn: Callable[[str], None]) -> None:
    """Writes the bundle's entry as the project's own row. A check that is not available here, a type a baseline cannot
    hold and a field the type has no column for are reported through `warn` and left out."""
    if not entry:
        return
    settings = _import_settings(db, entry, project=project, warn=warn)
    _write(db, profile_id=None, project_id=project.id, settings=settings)
