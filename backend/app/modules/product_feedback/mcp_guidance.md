Capture, triage and track enhancement requests: proposed solutions asked for by stakeholders, staff or support.

Model: a **request** is a *solution* someone wants; a Pain Point is the *problem* it addresses. A request has a lifecycle (`new` -> `under_review` -> `accepted` -> `delivered`, or `declined`; `duplicate` is set only by merging). It lives in a project or, where the organisation allows it, in the organisation's **inbox**. It carries an owner (a user or a group) and an optional external reference to the same item in a delivery tool (URL plus key). Delivery tracking itself stays in that tool.

Read workflow: `product_feedback_list_requests` (filter `status`, `open_only`, `search`), then `product_feedback_get_request` for detail and `allowed_next_statuses`; `product_feedback_list_request_versions` for history and `product_feedback_list_request_comments` for the discussion. `product_feedback_get_feedback_settings` says who may submit in the project.

Write workflow: `create_request` (only a title is needed) -> `update_request` (owner, description, external reference) -> `transition_request`. Link a request to the Pain Point it addresses and the Requirement that realises it with the core link tools.

Rules and gotchas:
- Submitting is open to project members unless the project restricted it to triagers; every other write needs the Feedback Triager role. A 403 means the caller lacks it.
- `transition_request` to `declined` needs a `comment`: it is stored as the decline reason. Moving to `delivered` is a person's judgement; do it only when asked.
- A move to `duplicate` is refused; duplicates are merged, not transitioned.
- A request's `owner` is `{"type": "user" | "org_group" | "project_group", "id": ...}`; `null` clears it.
- The organisation inbox tools answer 404 when an organisation administrator has switched the inbox off.
- There is no delete tool; archiving is a UI action.
