Maintain stakeholders, personas and stakeholder needs, and link them to the rest of a project.

Model: a **stakeholder** is a person or group with an interest in the product; a **persona** is an archetypal user; a **need** belongs to a stakeholder and can lead to requirements. Each has the lifecycle `draft` -> `active` -> `retired`. Stakeholders and personas may be shared from the organisation, so a project's list can include shared ones.

Read workflow:
1. `stakeholders_list_stakeholders`, `stakeholders_list_personas`, `stakeholders_list_stakeholder_needs`, then the matching `get_*` for detail.
2. For connections: `stakeholders_list_stakeholder_relationships`, `stakeholders_list_persona_relationships`, `stakeholders_list_incoming_relationships` (what points at a record), `stakeholders_list_stakeholder_personas`, `stakeholders_list_need_holders`, `stakeholders_list_need_requirements`.
3. Before adding a relationship call `stakeholders_list_relationship_kinds` (valid kinds and targets) and `stakeholders_list_relationship_targets` for the candidate target ids.

Write workflow: `create_*` -> `update_*` -> `activate_*`; `retire_*` ends use. Classify stakeholders with **stakeholder groups**: `stakeholders_list_stakeholder_groups` (flat; build the tree from `parent_group_id`), `create_stakeholder_group`, `update_stakeholder_group` (rename, move with `parent_group_id`), `add_stakeholder_to_group` / `remove_stakeholder_from_group`, and the `group_id` filter on `stakeholders_list_stakeholders` (includes groups beneath it unless `direct_only=true`). Link with `add_*_relationship`, `add_stakeholder_persona`, `add_need_holder` and `add_need_requirement` (records that a need gave rise to a requirement); each has a matching `remove_*`.

Rules and gotchas:
- All tools are project-scoped (`project_id`).
- Shared (organisation) personas and stakeholders can be hidden per project with `set_*_visibility`; `reset_*_visibility` removes the project override. This only changes this project's view, not the shared record. Pass `include_hidden=true` to list hidden ones.
- `owner` (and a persona's `champion`) is `{"type": "user" | "org_group" | "project_group", "id": ...}`, so a team can own a record; responses return the same shape plus `label`. A shared (organisation) record cannot name a project group. `null` clears it.
- A hidden persona is no longer scored or linkable in that project, so check before linking.
- Stakeholder groups are not user or project groups: they only classify stakeholders and grant nothing. These tools edit the project's own groups; the organisation's are read-only here. A group marked `exclusive_children` allows a stakeholder in only one of its child branches (409 otherwise). `delete_stakeholder_group` keeps the stakeholders and moves child groups up.
- Retire rather than delete stakeholders, personas and needs; there is no tool to delete them.
- No tool here is an approval, so none is gated by AI approval, but writes still need write mode and the caller's module role.
