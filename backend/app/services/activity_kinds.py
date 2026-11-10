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

Design decisions:
- An action in no map is kind `other`, so a filter by kind can never hide an event nobody classified, and a
  module that registers nothing still appears under Other.
- A kind filter is resolved to actions in Python and sent to the database as `action IN (...)` (with
  `NOT IN (all known)` for Other), so it narrows each source query instead of filtering after the merge.
- The version-derived entries (`created` for version 1, `updated` after) go through the same functions.

External dependencies: `modules.registry` (module contributions).
"""

from __future__ import annotations

from collections.abc import Iterable

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


def action_kinds() -> dict[str, str]:
    """Every known action with its kind: the core map overlaid with each registered module's own.

    Returns:
        `{action: kind}`. A module's entry wins over a core one for the same action (a module may know its
        own `approved` is something else).
    """
    from app.modules.registry import get_activity_action_kinds

    return {**CORE_ACTION_KINDS, **get_activity_action_kinds()}


def kind_of(action: str, known: dict[str, str] | None = None) -> str:
    """The kind of one action; `other` when nobody classified it.

    Args:
        action: An `AuditEvent.action` or a version-derived action (`created`, `updated`).
        known: The map from `action_kinds()`, passed by a caller classifying many entries.
    """
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
