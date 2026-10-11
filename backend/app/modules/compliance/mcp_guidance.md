Assess a project against compliance standards and evidence the result.

Model: an organisation owns **standards**; each standard has **versions** (`draft` -> `published` -> `retired`) holding **requirements** and **required actions**. A project is **assigned** one published version; that creates per-project requirement rows (`pcr_id`) and action assessments you then assess.

Read workflow (start here):
1. `compliance_list_standards` (org) -> `compliance_get_standard_version` / `compliance_list_requirements` for the content.
2. `compliance_get_project_status` for the project's overall position, then `compliance_list_non_compliant_requirements`, `compliance_list_pending_approvals`, `compliance_list_expiring_evidence`, `compliance_list_reviews_due` for what needs attention.
3. `compliance_get_standard_version_diff` compares two versions; `compliance_list_requirement_mappings` shows cross-standard mappings.

Write workflow, in order: assign (`compliance_assign_standard_to_project`, the project-level path; `compliance_admin_assign_standard_to_project` is the org-level admin path) -> set applicability (`compliance_update_requirement_applicability`) -> assess (`compliance_update_requirement_assessment` with a `justification`) -> attach evidence (`compliance_create_evidence`, optionally linking at creation, or `compliance_link_evidence_to_requirement`) -> `compliance_submit_requirement_for_approval`.

Rules and gotchas:
- Org-level tools (standards, versions, requirements, settings) need `organization_id`; assessment, evidence, review and project-level assignment tools need `project_id`. Use the ids from the matching list or get call.
- Edit a standard version's content while it is `draft`. Publishing (`compliance_publish_standard_version`) and retiring are deliberate steps: confirm with the user first.
- `compliance_approve_requirement` and `compliance_reject_requirement` are approvals, gated by AI approval (see the main skill). Never call them unless the user asked for that specific requirement. `compliance_submit_requirement_for_approval` only queues a decision and is not gated.
- Evidence can expire, so check `compliance_list_expiring_evidence` before reporting a project as compliant.
- Delete tools (`compliance_delete_*`) are destructive: name the item and confirm first. Prefer the `archive_*` tools, which can be undone with `unarchive_*`.
- Standard member/group role assignment, bulk import and evidence file upload are not available through MCP.
