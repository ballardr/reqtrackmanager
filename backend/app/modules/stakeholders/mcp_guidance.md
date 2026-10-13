Maintain stakeholders, personas and stakeholder needs, log engagements with them, and link them to the rest of a project.

Model: a **stakeholder** is a person or group with an interest in the product; a **persona** is an archetypal user; a **need** belongs to a stakeholder and can lead to requirements. Each has the lifecycle `draft` -> `active` -> `retired`. Stakeholders and personas may be shared from the organisation, so a project's list can include shared ones.

An **engagement** is one dated contact (email, call, meeting, workshop, interview, focus group, usability test, survey) with who took part, which personas it covered, and the pain points, needs and open questions it raised or answered. Engagements are project-scoped and have no lifecycle. The optional **research extras** (session prompts, anonymous participants, findings) exist only while that sub-component is on for the project; their tools answer 404 otherwise.

Read workflow:
1. `stakeholders_list_stakeholders`, `stakeholders_list_personas`, `stakeholders_list_stakeholder_needs`, then the matching `get_*` for detail.
2. For connections: `stakeholders_list_stakeholder_relationships`, `stakeholders_list_persona_relationships`, `stakeholders_list_incoming_relationships` (what points at a record), `stakeholders_list_stakeholder_personas`, `stakeholders_list_need_holders`, `stakeholders_list_need_requirements`.
3. Before adding a relationship call `stakeholders_list_relationship_kinds` (valid kinds and targets) and `stakeholders_list_relationship_targets` for the candidate target ids.

Write workflow: `create_*` -> `update_*` -> `activate_*`; `retire_*` ends use. Classify stakeholders with **stakeholder groups**: `stakeholders_list_stakeholder_groups` (flat; build the tree from `parent_group_id`), `create_stakeholder_group`, `update_stakeholder_group` (rename, move with `parent_group_id`), `add_stakeholder_to_group` / `remove_stakeholder_from_group`, and the `group_id` filter on `stakeholders_list_stakeholders` (includes groups beneath it unless `direct_only=true`). Link with `add_*_relationship`, `add_stakeholder_persona`, `add_need_holder` and `add_need_requirement` (records that a need gave rise to a requirement); each has a matching `remove_*`.

Engagement workflow: `create_engagement` (a quick log needs only title, channel, date and `stakeholder_ids`; pass `group_ids` to aim it at a stakeholder group and add that group's current members), then `add_engagement_participant` / `add_engagement_persona` / `add_engagement_audience` as needed, and `add_engagement_outcome` with `kind` `raised` (pain point, need or open question) or `answered` (open question); find candidate ids with `stakeholders_list_relationship_targets`. `stakeholders_list_stakeholder_engagements` is a stakeholder's timeline, and `stakeholders_list_engagements` filters by channel, stakeholder, persona, date range or `retention_due`. Research extras: `add_engagement_prompt` / `update_engagement_prompt`, `add_anonymous_participant`, `create_research_finding` / `update_research_finding` and `add_finding_outcome`.

Rules and gotchas:
- All tools are project-scoped (`project_id`).
- Shared (organisation) personas and stakeholders can be hidden per project with `set_*_visibility`; `reset_*_visibility` removes the project override. This only changes this project's view, not the shared record. Pass `include_hidden=true` to list hidden ones.
- `owner` (and a persona's `champion`) is `{"type": "user" | "org_group" | "project_group", "id": ...}`, so a team can own a record; responses return the same shape plus `label`. A shared (organisation) record cannot name a project group. `null` clears it.
- A hidden persona is no longer scored or linkable in that project, so check before linking.
- Stakeholder groups are not user or project groups: they only classify stakeholders and grant nothing. These tools edit the project's own groups; the organisation's are read-only here. A group marked `exclusive_children` allows a stakeholder in only one of its child branches (409 otherwise). `delete_stakeholder_group` keeps the stakeholders and moves child groups up.
- Retire rather than delete stakeholders, personas and needs; there is no tool to delete them. There is also no tool to delete an engagement, prompt, anonymous participant or finding: erasing possible personal data is a human action in the UI.
- Engagement notes, summaries and finding text can quote people, so keep them to what the record needs. An anonymous participant is a label such as "Participant 3": never put a real name or contact detail in it, and name a stakeholder as a participant instead when the person matters.
- Adding an audience group copies the group's members at that moment as participants; later membership changes do not alter the engagement. Removing the audience keeps those participants.
- No tool here is an approval, so none is gated by AI approval, but writes still need write mode and the caller's module role.
