Capture the "why" above requirements: strategies, future states, pain points, guiding principles and open questions.

Five artefact types, each with its own lifecycle (read the current `status` before choosing a transition tool):
- **Strategy**: `draft` -> `proposed` -> `under_review` -> `approved` -> `active` -> `superseded` / `retired`.
- **Future state**: same shape as strategy.
- **Guiding principle**: `draft` -> `proposed` -> `approved` -> `active` -> `superseded` / `retired`.
- **Pain point**: `submitted` -> `triaged` -> `accepted` -> `addressed` -> `closed`; also `rejected` or `duplicate`.
- **Open question**: `open` -> `investigating` -> `ready_for_decision` -> `resolved`, or `withdrawn`.

Read workflow: `list_<type>` then `get_<type>`; `list_<type>_relationships` shows how it connects to other artefacts. Reports (`..._report`) answer cross-cutting questions: prioritisation, strategy cascade and alignment gaps, coverage, roadmap, open question register, change history, summary, upgrade drivers.

Write workflow:
- `create_<type>` then `update_<type>`. Non-decisive transitions are one tool each (`propose_*`, `submit_*_for_review`, `send_*_back`, `supersede_*`, `triage_pain_point`, `accept_pain_point`, `investigate_open_question`, and so on). Call a transition only from a status that allows it; a conflict error means the status is wrong, so re-read the record.
- Link artefacts with `create_<type>_relationship` (the `kind` decides the target type; list the existing relationships first to avoid duplicates). Supersession has its own `create_*_supersession` tools.
- Score a pain point with `context_strategy_set_pain_point_scores`: it **replaces** all scores. Fetch the current scores and the project's scoring levels first, and use either all-persona or per-persona entries, never both.

Rules and gotchas:
- Decisive tools are approvals, gated by AI approval (see the main skill): `approve_strategy`, `approve_future_state`, `activate_guiding_principle`, `retire_guiding_principle`, `resolve_open_question`. Only call them when the user asked for that specific item.
- Everything here is project-scoped (`project_id`). Organisation-level strategies, future states and principles are not reachable through MCP.
- Reports take `include_children` to roll up child projects.
- Comments and file uploads are not available through MCP.
