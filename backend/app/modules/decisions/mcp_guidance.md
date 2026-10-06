Read and approve architectural/product decision records (ADR-style) for a project.

Model: a project holds **decisions** with a type (`decisions_list_decision_types`), a status (`draft`, `proposed`, `under_review`, `approved`, `rejected`, `superseded`), comments, files and relationships to other artefacts. An organisation holds reusable **templates** (`decisions_list_decision_templates`, e.g. Nygard / MADR / Y-Statement).

Read workflow:
1. `decisions_list_decisions` (project) to find records; `decisions_get_decision` for context, options considered, chosen option and rationale.
2. `decisions_list_decision_relationships` for what the decision supersedes or links to; `decisions_list_decision_comments` and `decisions_list_decision_files` for discussion and attachments.
3. `decisions_list_decision_types` to see the project's valid types (a child project may inherit its parent's).

Rules and gotchas:
- There are no create, edit or submit tools: decisions are authored in the UI. Do not offer to create one.
- `decisions_approve_decision` and `decisions_reject_decision` are approvals, gated by AI approval (see the main skill) and by the caller holding the decision approve permission. Only call them when the user explicitly asks about that specific decision, and pass the reason the user gave.
- Check the decision's status before acting: only a decision awaiting a verdict can be approved or rejected.
- A superseded decision is history; follow its relationships to the decision that replaced it before quoting it as current.
