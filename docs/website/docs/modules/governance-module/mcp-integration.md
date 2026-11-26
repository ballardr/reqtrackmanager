---
sidebar_position: 56
---

# AI assistant (MCP) integration

Traceability & Governance contributes 29 tools to ReqTrackManager's [MCP server](../../api-integrations/ai-assistants-mcp/overview.md), the same mechanism an AI assistant like Claude Code uses to read and update the other modules. They register automatically when the module is enabled for an organisation. Tool names start with `traceability_`. Tools for a [sub-component](./overview.md#parts-of-the-module) that is switched off answer *not found*.

Writes follow the usual MCP write mode: the server must have writes enabled, and the signed-in account's own permission decides what it may change. A project tool needs **Manage project governance** and an organisation tool needs **Manage organisation governance**.

**No tool approves a record or finalises a baseline.** Deleting a profile, and adding or removing an exemption, also have no tool, because each lifts a control the organisation enforces and stays a person's act in the application.

## What's covered

| Category | Tools |
| --- | --- |
| Read a project | `get_governance_health`, `get_governance_health_settings`, `list_project_governance_profiles`, `get_project_approval_policies`, `get_project_review_policies`, `get_project_baseline_policy`, `preview_baseline_checks` |
| Write a project | `set_governance_health_settings`, `refresh_governance_health`, `set_project_governance_profile_choice`, `set_project_approval_policy`, `set_project_review_policy`, `set_project_baseline_policy` |
| Read the organisation | `list_governance_profiles`, `get_governance_profile`, `get_governance_health_defaults`, `get_profile_lifecycle_policy`, `get_profile_stage_workflow_policy`, `get_profile_approval_policy`, `get_profile_review_policy`, `get_profile_baseline_policy` |
| Write the organisation | `create_governance_profile`, `update_governance_profile`, `set_governance_profile_targets`, `set_governance_health_defaults`, `set_profile_lifecycle_required`, `set_profile_lifecycle_skip`, `set_profile_stage_workflow_policy`, `set_profile_approval_policy`, `set_profile_review_policy`, `set_profile_baseline_policy` |

## What you can ask for

| You ask | Tool it maps to |
| --- | --- |
| "How healthy is this project?" | `get_governance_health` |
| "Which profiles apply to this project, and why?" | `list_project_governance_profiles` |
| "Who may approve a Decision here, and from which profile?" | `get_project_approval_policies` |
| "Would a stage baseline pass right now?" | `preview_baseline_checks` |
| "Require a description on every Requirement before a stage baseline." | `set_project_baseline_policy` |
| "Create an Opt-in profile for safety-critical projects." | `create_governance_profile` |

## Cautions

- Creating an **Enforced** profile, changing its policy or targets, or setting a profile's mode to Enforced changes the rules for every project it reaches. An assistant should confirm with the person first.
- A snapshot's check results can be **carried forward** from an earlier run. The health read says which, and an assistant should not describe a carried-forward result as current.
- `set_governance_health_settings` replaces every field, so an assistant sends the values it wants to keep.

See the [Agent skill](../../api-integrations/ai-assistants-mcp/agent-skill.mdx) for the generated, always-current list of module tools.
