Record, assess, treat and review project risks.

Model: a **risk** has a lifecycle (`identified` -> `assessed` -> `treatment_planned` -> `treatment_in_progress` -> `mitigated`, or an outcome such as `accepted`, `transferred`, `avoided`, `realised`, `rejected`, then `closed`). Its **inherent** and **residual** ratings are derived from Likelihood, Consequence and (optionally) Detectability levels; ratings are never set directly. A requirement, design or action that **mitigates or treats** the risk carries a verdict: `proposed` (just linked), `effective`, `ineffective` or `needs_reassessment`. Only `effective` counts as treatment. The owner or a Risk Manager also records periodic **reviews**.

Read workflow:
1. `risk_management_list_risks` (filter `effectively_treated=false` for untreated risks, `review_overdue=true` for overdue reviews), then `risk_management_get_risk` for detail and `allowed_next_statuses`.
2. `risk_management_list_risk_treatments` for what treats it and why a verdict needs reassessment; `risk_management_list_risk_reviews` and `risk_management_list_risk_versions` for history.
3. Before setting ratings call `risk_management_get_risk_scoring_scheme` for the level ids.

Write workflow: `create_risk` -> `update_risk` (set levels, owner, strategy) -> `transition_risk`. Link treatments with the core link tools (a requirement `Mitigates` the risk; the risk is `Treated by` an action), then `assess_risk_treatment`. Finish a review with `record_risk_review`.

Reports (`risk_management_get_*_report`, project-level, read-only) answer cross-cutting questions in one call: the risk register (filter by status, type), risk exposure (inherent against residual rating, highest remaining risks, risks with no rating), treatment coverage (risks with no effective treatment, or resting on a verdict to reassess) and the review schedule (overdue, due soon, no review scheduled). Prefer a report over listing and fetching every risk.

Rules and gotchas:
- A move needs its facts first: `assessed` needs an inherent rating, `treatment_planned` an owner and strategy, `mitigated` a residual rating and at least one `effective` treatment, `accepted` a residual rating and acceptance criteria. A 409 names what is missing.
- `transition_risk` to `accepted` is an approval: it needs the Risk Acceptor role and AI approval enabled on the project and organisation. Only do it when the user explicitly asks, and pass their reason as `comment`.
- An `accepted` risk's levels, acceptance criteria and strategy cannot be edited; move it back to `assessed` first.
- A change to a linked requirement moves its `effective` verdict to `needs_reassessment`. Reassess it with `assess_risk_treatment`; do not simply re-mark it effective without checking the change.
- `record_risk_review` with `confirmed` fails while any treatment `needs_reassessment`; reassess first or record `reassessed`. `next_review_date` is required (a future date, or null for none).
- A risk's `owner` is `{"type": "user" | "org_group" | "project_group", "id": ...}`, so a team can be accountable; responses return the same shape plus `label`. `null` clears it. Members of an owner group may assess treatments and record reviews, as the owner can.
- There is no delete tool. Do not invent level or type ids; read them.
