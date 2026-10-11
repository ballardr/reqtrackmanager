Maintain stakeholders, personas and stakeholder needs, and link them to the rest of a project.

Model: a **stakeholder** is a person or group with an interest in the product; a **persona** is an archetypal user; a **need** belongs to a stakeholder and can lead to requirements. Each has the lifecycle `draft` -> `active` -> `retired`. Stakeholders and personas may be shared from the organisation, so a project's list can include shared ones.

Read workflow:
1. `stakeholders_list_stakeholders`, `stakeholders_list_personas`, `stakeholders_list_stakeholder_needs`, then the matching `get_*` for detail.
2. For connections: `stakeholders_list_stakeholder_relationships`, `stakeholders_list_persona_relationships`, `stakeholders_list_incoming_relationships` (what points at a record), `stakeholders_list_stakeholder_personas`, `stakeholders_list_need_holders`, `stakeholders_list_need_requirements`.
3. Before adding a relationship call `stakeholders_list_relationship_kinds` (valid kinds and targets) and `stakeholders_list_relationship_targets` for the candidate target ids.

Write workflow: `create_*` -> `update_*` -> `activate_*`; `retire_*` ends use. Link with `add_*_relationship`, `add_stakeholder_persona`, `add_need_holder` and `add_need_requirement` (records that a need gave rise to a requirement); each has a matching `remove_*`.

Rules and gotchas:
- All tools are project-scoped (`project_id`).
- Shared (organisation) personas and stakeholders can be hidden per project with `set_*_visibility`; `reset_*_visibility` removes the project override. This only changes this project's view, not the shared record. Pass `include_hidden=true` to list hidden ones.
- A hidden persona is no longer scored or linkable in that project, so check before linking.
- Retire rather than delete; there are no delete tools.
- No tool here is an approval, so none is gated by AI approval, but writes still need write mode and the caller's module role.
