"""
Module: services.activity_kinds

The *kind* of an activity event ("how it changed"): the small fixed vocabulary the project History page
filters and labels by, over the open-ended `AuditEvent.action` strings.

Responsibilities:
- Name the kinds (`KIND_LABELS`) and map every core action to one (`CORE_ACTION_KINDS`).
- Merge in the actions a module declares through `ModuleDefinition.activity_action_kinds`
  (`action_kinds`), so a module never edits this file.
- Turn a set of wanted kinds into the actions to match (`actions_for_kinds`), and an action into its kind
  (`kind_of`).
- Group the entity types of the events (`classify_entity`, `entity_groups`): a registered record type under its
  owning module (or Core), anything else under one metadata group (links and files, tags and places, access,
  structure and settings, other), so the Type filter is a short two-level list.

Design decisions:
- An action in no map is kind `other`, so a filter by kind can never hide an event nobody classified, and a
  module that registers nothing still appears under Other.
- A kind filter is resolved to actions in Python and sent to the database as `action IN (...)` (with
  `NOT IN (all known)` for Other), so it narrows each source query instead of filtering after the merge.
- The version-derived entries (`created` for version 1, `updated` after) go through the same functions.
- A kind is decided by the entity type first: every event of a link, tag, role or group entity is *Links and
  files*, *Tags and places* or *Access* whatever its action (`created` of a link is a link event, never *Created*),
  and the action decides only for a record's own events and for the structure and settings groups.
- Metadata entity types are a registry: the core map here, the `_link` and `_definition` naming conventions, and
  `ModuleDefinition.activity_metadata_types` for a module's own, so a module never edits this file. A type in none
  of them is the metadata group Other, so it stays reachable.

External dependencies: `modules.registry` (module contributions).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

CREATED = "created"
EDITED = "edited"
STATUS = "status"
LINKS = "links"
TAGS = "tags"
ACCESS = "access"
COMMENTS = "comments"
DELETED = "deleted"
OTHER = "other"

#: Kind key to the plural label the filter and the Event column show (the frontend holds the same keys in
#: `ACTIVITY_KIND_LABEL`; a test pins the two together).
KIND_LABELS: dict[str, str] = {
    CREATED: "Created",
    EDITED: "Edited",
    STATUS: "Status changes",
    LINKS: "Links and files",
    TAGS: "Tags and places",
    ACCESS: "Access",
    COMMENTS: "Comments",
    DELETED: "Deleted",
    OTHER: "Other",
}

CORE_ACTION_KINDS: dict[str, str] = {
    **dict.fromkeys(("created", "create", "added", "uploaded", "duplicated", "copied", "imported", "imported_from_bundle",
                     "merged_from_bundle", "records_imported", "requirements_imported", "invited", "signed_up"), CREATED),
    **dict.fromkeys(("updated", "renamed", "rename", "reordered", "moved", "moved_to_project", "parented", "reclassified",
                     "version_saved", "settings_updated", "terminology_updated", "report_config_updated", "scored",
                     "set", "merged", "owner_changed", "reassigned", "principal_reassigned", "layout_changed",
                     "code_updated", "code_changed", "audience_changed", "visibility_hidden", "visibility_cleared",
                     "visibility_reset", "override_saved", "override_reset", "weight_override_set",
                     "weight_override_cleared", "review_deadline_set", "review_recorded", "reviewed",
                     "review_response_submitted", "cast", "clarified", "assessed", "treatment_assessed",
                     "scheduled", "branding_updated", "default_template_updated", "advanced_settings_updated",
                     "applicability_changed", "applicability_default_changed", "marked_duplicate", "revalidated"), EDITED),
    **dict.fromkeys(("approved", "rejected", "submitted", "submitted_for_review", "submitted_for_approval", "withdrawn",
                     "sent_back", "status_changed", "completed", "uncompleted", "completion_cleared_by_review",
                     "completion_cleared_via_change_request", "closed", "resolved", "published", "unpublished",
                     "activated", "retired", "superseded", "proposed", "accepted", "archived", "unarchived", "restored",
                     "investigating", "triaged", "ready_for_decision", "addressed", "workflow_changed", "reconciled",
                     "approval_invalidated", "draft_discarded", "acknowledged", "enabled", "disabled",
                     "treatment_needs_reassessment"), STATUS),
    **dict.fromkeys(("linked", "unlinked", "relationship_added", "relationship_removed", "requirement_linked",
                     "requirement_unlinked", "action_linked", "action_unlinked", "evidence_linked", "evidence_unlinked",
                     "file_attached", "file_linked", "file_unlinked", "comment_file_attached", "comment_file_removed",
                     "link_type_changed", "represents_added", "represents_removed", "policy_links_changed"), LINKS),
    **dict.fromkeys(("tagged", "untagged", "placed", "unplaced"), TAGS),
    **dict.fromkeys(("granted", "revoked", "role_granted", "role_revoked", "role_assigned", "member_added",
                     "member_removed", "nested_group_added", "holder_added", "holder_removed", "watcher_added",
                     "watcher_removed", "inherited_access_materialized"), ACCESS),
    **dict.fromkeys(("comment_added", "comment_edited"), COMMENTS),
    **dict.fromkeys(("deleted", "delete", "removed", "erased"), DELETED),
}


#: Audit events kept for the audit trail only, never listed on a History or Activity page: the discussion shows the
#: comment itself (`services.changes` merges the comments in), and a reaction or a removed attachment is not a change to
#: the record. Written by `services.engagement.audit_comment`.
AUDIT_TRAIL_ONLY_ACTIONS: frozenset[str] = frozenset({
    "comment_added", "comment_edited", "comment_reacted", "comment_reaction_removed", "comment_attachment_removed",
})
#: The record types whose comments those events are written against.
AUDIT_TRAIL_ONLY_ENTITY_TYPES: frozenset[str] = frozenset({"requirement", "change_request", "requirement_action"})


SECTION_RECORDS = "records"
SECTION_METADATA = "metadata"
CORE_RECORDS_KEY = "records:core"

#: Metadata group key to `(label, kind it forces)`, in display order. A forced kind is the kind of every event of
#: the group's entity types; `None` leaves the kind to the action.
METADATA_GROUPS: dict[str, tuple[str, str | None]] = {
    "links": ("Links and files", LINKS),
    "tags": ("Tags and places", TAGS),
    "access": ("Access", ACCESS),
    "structure": ("Structure and settings", None),
    "other": ("Other", None),
}

#: Core entity types that are not record types, with their metadata group.
CORE_METADATA_TYPES: dict[str, str] = {
    **dict.fromkeys(("artefact_link", "requirement_link", "requirement_action_link", "file_asset", "file"), "links"),
    **dict.fromkeys(("tag",), "tags"),
    **dict.fromkeys((
        "user_project_role", "user_module_role", "user_org_role", "user_server_role", "org_group_project_role",
        "group_module_role", "user_custom_role_grant", "group_custom_role_grant", "project_group", "org_group",
        "project_member_source", "pending_invite", "personal_access_token", "user", "credential_reset", "imported_person",
    ), "access"),
    **dict.fromkeys((
        "project", "project_stage", "project_component", "project_category", "stage_workflow", "stage_phase_plan",
        "component_stage_state", "overview_layout", "nav_labels", "project_module", "project_module_subcomponent",
        "tag_settings", "pain_point_submission_settings", "project_feedback_settings", "record_sensitivity_policy",
        "scoring_model", "scoring_level", "scoring_axis", "scoring_threshold_set", "scoring_model_default",
        "scoring_enabled_models", "scoring_cell_rating_set", "scoring_band_set", "report_layout", "report_pack",
        "report_pack_set", "report_snippet", "report_folder", "report_placement", "report_run", "generated_report",
        "request_channel", "request_channel_definition", "external_system", "artefact_type_link_rule", "restore",
        "change_request_task", "change_request_vote", "organization_module", "organization_module_subcomponent",
        "organization", "organization_dashboard", "announcement", "policy", "report_font", "server_module_default", "system",
    ), "structure"),
}

#: Suffix conventions, so a new link family or vocabulary needs no entry: an entity type ending `_link` is a link
#: event type (it must also have an `activity_link_ends` reader) and one ending `_definition` is project structure.
_SUFFIX_GROUPS: tuple[tuple[str, str], ...] = (("_link", "links"), ("_definition", "structure"))


@dataclass(frozen=True)
class EntityGroup:
    """Where one event entity type sits in the Type filter.

    Attributes:
        key: `records:<module key>` (`records:core` for a core record type) or `metadata:<group>`.
        label: The heading: the owning module's name, `Core`, or the metadata group's label.
        section: `records` or `metadata`.
        forced_kind: The kind every event of this entity type has, or `None` when the action decides.
    """

    key: str
    label: str
    section: str
    forced_kind: str | None = None


def _metadata_group(group: str) -> EntityGroup:
    label, forced = METADATA_GROUPS[group]
    return EntityGroup(f"{SECTION_METADATA}:{group}", label, SECTION_METADATA, forced)


def classify_entity(entity_type: str) -> EntityGroup:
    """The Type-filter group of an event's entity type.

    Args:
        entity_type: An `AuditEvent.entity_type` (or `requirement` / `change_request` for version entries).

    Returns:
        The owning module's records group for a registered record type, else a metadata group (the core map, a
        module's declaration, then the naming conventions), else metadata Other.
    """
    from app.modules.registry import artefact_type_module, get_activity_metadata_types, get_all_registered_artefact_types

    if entity_type in get_all_registered_artefact_types():
        module = artefact_type_module(entity_type)
        if module is None:
            return EntityGroup(CORE_RECORDS_KEY, "Core", SECTION_RECORDS)
        return EntityGroup(f"{SECTION_RECORDS}:{module.key}", module.name, SECTION_RECORDS)
    group = get_activity_metadata_types().get(entity_type) or CORE_METADATA_TYPES.get(entity_type)
    if group is None:
        group = next((name for suffix, name in _SUFFIX_GROUPS if entity_type.endswith(suffix)), "other")
    return _metadata_group(group if group in METADATA_GROUPS else "other")


def entity_groups(entity_types: Iterable[str]) -> list[dict[str, object]]:
    """The two-level Type list of a set of entity types.

    Args:
        entity_types: The entity types the project has events for.

    Returns:
        Groups in display order (Core, then the other modules by name, then the metadata groups in
        `METADATA_GROUPS` order, empty groups omitted), each `{key, label, section, types}` with its types sorted.
    """
    found: dict[str, tuple[EntityGroup, list[str]]] = {}
    for entity_type in sorted(set(entity_types)):
        group = classify_entity(entity_type)
        found.setdefault(group.key, (group, []))[1].append(entity_type)
    metadata_order = {f"{SECTION_METADATA}:{key}": index for index, key in enumerate(METADATA_GROUPS)}

    def order(item: tuple[EntityGroup, list[str]]) -> tuple[int, int, str]:
        group = item[0]
        if group.section == SECTION_METADATA:
            return 1, metadata_order[group.key], group.label
        return 0, 0 if group.key == CORE_RECORDS_KEY else 1, group.label.lower()

    return [
        {"key": group.key, "label": group.label, "section": group.section, "types": types}
        for group, types in sorted(found.values(), key=order)
    ]


def is_group_key(key: str) -> bool:
    """Whether `key` names a Type-filter group that exists (a registered module's records, Core, or a metadata group)."""
    from app.modules.registry import get_module_registry

    section, _, name = key.partition(":")
    if section == SECTION_METADATA:
        return name in METADATA_GROUPS
    return section == SECTION_RECORDS and (name == "core" or name in get_module_registry())


def types_in_groups(entity_types: Iterable[str], group_keys: Iterable[str]) -> set[str]:
    """The entity types, of those given, that belong to any of the named groups (an unknown key matches none)."""
    wanted = set(group_keys)
    return {entity_type for entity_type in entity_types if classify_entity(entity_type).key in wanted}


def forced_kind_types() -> dict[str, str]:
    """`{entity type: kind}` for every entity type whose events all have one kind, as far as they can be listed.

    Only the explicitly mapped types are listed (core map and module declarations); a type matched by a naming
    convention is found by `forced_kind_suffixes`.
    """
    from app.modules.registry import get_activity_metadata_types

    forced: dict[str, str] = {}
    for entity_type, group in {**CORE_METADATA_TYPES, **get_activity_metadata_types()}.items():
        kind = METADATA_GROUPS.get(group, ("", None))[1]
        if kind is not None:
            forced[entity_type] = kind
    return forced


def forced_kind_suffixes() -> dict[str, str]:
    """`{entity type suffix: kind}` for the naming conventions whose group forces a kind (`_link` -> links)."""
    return {
        suffix: kind for suffix, group in _SUFFIX_GROUPS if (kind := METADATA_GROUPS[group][1]) is not None
    }


def action_kinds() -> dict[str, str]:
    """Every known action with its kind: the core map overlaid with each registered module's own.

    Returns:
        `{action: kind}`. A module's entry wins over a core one for the same action (a module may know its
        own `approved` is something else).
    """
    from app.modules.registry import get_activity_action_kinds

    return {**CORE_ACTION_KINDS, **get_activity_action_kinds()}


def kind_of(action: str, known: dict[str, str] | None = None, entity_type: str | None = None) -> str:
    """The kind of one event; `other` when nobody classified it.

    Args:
        action: An `AuditEvent.action` or a version-derived action (`created`, `updated`).
        known: The map from `action_kinds()`, passed by a caller classifying many entries.
        entity_type: The event's entity type; given, a link, tag, role or group event has its group's kind
            whatever the action (`created` of a link is *Links and files*).
    """
    if entity_type is not None:
        forced = classify_entity(entity_type).forced_kind
        if forced is not None:
            return forced
    return (known if known is not None else action_kinds()).get(action, OTHER)


def actions_for_kinds(kinds: Iterable[str]) -> tuple[set[str], bool]:
    """The actions a kind filter matches.

    Args:
        kinds: Wanted kind keys (validated by the caller against `KIND_LABELS`).

    Returns:
        `(actions, include_other)`: the listed actions of the wanted kinds, and whether an action no map knows
        is also wanted (the `other` kind).
    """
    wanted = set(kinds)
    known = action_kinds()
    return {action for action, kind in known.items() if kind in wanted}, OTHER in wanted
