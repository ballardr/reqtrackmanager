Read and approve architectural/product decision records (ADR-style) for a project.

Model: a project holds **decisions** with a type (`decisions_list_decision_types`), a status (`draft`, `proposed`, `under_review`, `approved`, `rejected`, `superseded`), comments, files and relationships to other artefacts. An organisation holds reusable **templates** (`decisions_list_decision_templates`, e.g. Nygard / MADR / Y-Statement).

Read workflow:
1. `decisions_list_decisions` (project) to find records; `decisions_get_decision` for context, options considered, chosen option, rationale and the long-form `document`.
2. `decisions_list_decision_relationships` for what the decision supersedes or links to; `decisions_list_decision_comments` and `decisions_list_decision_files` for discussion and attachments.
3. `decisions_list_decision_types` to see the project's valid types (a child project may inherit its parent's).

Reports (`decisions_get_*_report`) answer cross-cutting questions, project-level only: the decision register (filter by status, type, date range), approval ageing (what has waited longest for a verdict), the decision log (decisions made in a period, with rationale) and rationale coverage (decisions with no linked artefact, requirements with no linked decision). Prefer a report over listing and fetching every decision.

Rules and gotchas:
- Decision text (statement, context, options, rationale, consequences, assumptions, constraints and `document`) is Markdown source: tables, code and lists are plain syntax, and a fenced block that starts with ```mermaid is a diagram, so read its text as the diagram's definition. Quote or summarise it; do not rewrite the marks.
- There are no create, edit or submit tools: decisions are authored in the UI. Do not offer to create one.
- `decisions_approve_decision` and `decisions_reject_decision` are approvals, gated by AI approval (see the main skill) and by the caller holding the decision approve permission. Only call them when the user explicitly asks about that specific decision, and pass the reason the user gave.
- Check the decision's status before acting: only a decision awaiting a verdict can be approved or rejected.
- A superseded decision is history; follow its relationships to the decision that replaced it before quoting it as current.
- A project may turn off Proposed and Under review; a Decision then goes from `draft` to `approved` through the same approval, with the same permission and comment. A refused move names the allowed next states.
- A person may skip steps of a record's lifecycle in the application (a project setting, with a reason); an MCP tool never does. A refused move names the allowed next states: choose one of those.
