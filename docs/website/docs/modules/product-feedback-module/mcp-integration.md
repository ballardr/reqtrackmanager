---
sidebar_position: 47
---

# AI assistant (MCP) integration

Product Feedback contributes 34 tools to ReqTrackManager's [MCP server](../../api-integrations/ai-assistants-mcp/overview.md), the mechanism an AI assistant such as Claude Code uses to read and update records. They register when the module is enabled for an organisation, and every one follows the usual MCP write mode: the server must have writes enabled and the signed-in account's own role decides what it may change.

## What's covered

| Category | Count | Covers |
| --- | --- | --- |
| Read | 13 | Listing and fetching requests (filters include status, open only, search, scored or unscored, and a missing criterion), versions, comments, the scoring scheme, the demand breakdown (paged), the close-the-loop view, open loops, merges, references, the external system and channel lists, and the project's submission setting. |
| Create / update / status | 3 | Creating a request, changing it, and moving it between statuses. Declining needs a reason. |
| Merge | 2 | Merging a request into another, and undoing it. |
| Close the loop | 1 | Marking requesters told, or withdrawing it. |
| References and channels | 4 | Adding, changing and removing an external reference, and setting a requester's channel. |
| Comments | 1 | Adding a comment. |
| Organisation inbox | 5 | Listing and creating inbox requests, the inbox's scoring scheme and system list, and moving an inbox request into a project. |
| Reports | 5 | The five [reports](./reports.md), read-only. |

Requesters, Pain Points and Requirements are linked with the **core link tools** (link types **Requested by**, **Addresses** and **Realised by**). There is **no tool to delete or archive a request**, and none that defines or hides scoring criteria: those stay in the app. Moving a request to **Delivered** is left to a person's judgement; an assistant should do it only when asked.

## What you can ask for

| You ask | Tool it maps to |
| --- | --- |
| "What are our most-requested enhancements?" | `product_feedback_get_demand_ranking_report` |
| "Which requests have no Pain Point?" | `product_feedback_get_unlinked_requests_report` |
| "Which requests are still unscored on Ease?" | `product_feedback_list_requests` (`missing_axis`) |
| "Who asked for ENH-001, and how?" | `product_feedback_get_request_demand` |
| "Merge ENH-004 into ENH-001." | `product_feedback_merge_request` |
| "Who still needs to hear about the delivered requests?" | `product_feedback_list_open_loops` |
| "Mark Priya's ask as told." | `product_feedback_mark_requesters_informed` |
| "Add the Jira epic FAL-214 as the delivery reference." | `product_feedback_add_request_reference` |
| "What has been waiting more than 30 days?" | `product_feedback_get_triage_ageing_report` |

## Where this fits

See [Reports](./reports.md) for what each report returns, and [AI assistants (MCP) → Agent skill](../../api-integrations/ai-assistants-mcp/agent-skill.mdx) for the usage guidance an assistant is given for this module.
