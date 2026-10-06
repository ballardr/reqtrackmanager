# Platform Enhancements (October 2026) — Plan

**Status:** Decisions Q1–Q13 answered by the user 2026-10-06. Phases 1–5 implemented; Phase 5b (link authoring, any-to-any with restrictions from both sides) added 2026-10-06 after a link-coverage audit; the rest is not implemented. Written from eight user notes, each checked against the current code.
**Decision tags:** items marked **Decided by: User** were answered in the 2026-10-06 review (§3); everything else is **Decided by: Agent** and can be revisited on the agent's own judgement.

## Status / Resume Here

5 / 14 phases complete (Phases 1–5 done 2026-10-06, awaiting commit). **Phase 5b is next, then 5c** (both must land before Phase 6: the shared panel's add row is built on them). Phase 10 grew after review (three tiers, placeholders, ancestor fallback); Phase 3 shrank (no dashboard). Phase 11 (project Modules tab e2e coverage) was added after review; Phase 12 is the closing website-docs reconciliation and runs last.

| # | Phase | Note | Status |
|---|-------|------|--------|
| 1 | MCP agent skill + drift enforcement | N5 | [x] |
| 2 | Org-level member-edit notifications | N3 | [x] |
| 3 | Request-rate and DB read/write metrics | N2 | [x] |
| 4 | Personal project-nav ordering, "More", per-project override | N4 | [x] |
| 5 | Link-type direction field + link graph backend (+ MCP tool) | N1 | [x] |
| 5b | Any-to-any linking, restrictions from both sides (per link type, per artefact type), delete-in-use dialog, generic link authoring, coverage guard | N1 | [ ] |
| 5c | Project-level link types and rules, hide org types, org switch to forbid | N1 | [ ] |
| 6 | Shared Links panel, detail-page aside, migration of existing sections | N1 | [ ] |
| 7 | Trace tree and map views | N1 | [ ] |
| 8 | Decision Management reports | N6 | [ ] |
| 9 | Neutral report document model + DOCX export | N7 | [ ] |
| 10 | Per-report-type content: template, project, org tiers + placeholders | N8 | [ ] |
| 11 | Project Modules tab e2e coverage | N9 | [ ] |
| 12 | Docs website reconciliation for the whole branch | all | [ ] |

## 1. Summary of the review (read this first)

| Note | Verdict | Where I disagree or reshaped it |
|------|---------|---------------------------------|
| N1 Links panel + graph | Do it; biggest item | A force-directed "spider web" is the wrong default (unreadable past ~30 nodes). Ship list → trace tree → bounded layered map. The panel must replace the **nine** link UIs that exist today, not add a tenth. |
| N2 Metrics | Half already exists | Requests/min needs no code (`http_requests_total` exists). DB reads/writes need new counters. "Per 15 min" is a query window, not a metric. No Grafana dashboard exists; user chose counters only, no bundled dashboard. |
| N3 PM notification | Do it | Needs coalescing or bulk adds spam managers. "Org level ability" must be defined precisely (below). |
| N4 Nav order | Do it | "Hide" should mean *move behind "More"*, never remove (a hidden Admin link strands the user). Drag-only reordering fails accessibility. |
| N5 MCP skill | Do it | "Update the skill whenever a tool is added" as an instruction alone **will rot**: tools are also added *implicitly* (every `ReportDefinition` and module `mcp_tools` entry becomes an MCP tool, e.g. Phase 8 adds some without touching `mcp-server/`). Enforce with a test. |
| N6 Decision reports | Do it; cheap | The report framework already exists; Decisions has no reports at all. Mostly declarations. |
| N7 DOCX | Do it | Adding a second renderer next to the PDF one invites layout drift. Introduce one neutral document model both consume. |
| N8 Per-type chapters | Do it | This is the open question the framework deliberately deferred (Module 1 Phase 12b, "Open question 1"). User chose all three tiers plus placeholders, so this is the largest reporting phase; see Phase 10. |

### Interpretation of imprecise wording (CLAUDE.md: inputs may be casual)

- **"each component"** (N1): "component" already means a requirement grouping in this product. Read as *every artefact detail page* (requirement, action, and every module artefact: pain point, decision, persona, …). Change requests have no `ArtefactLink` rows today, so they are out of scope unless the user says otherwise.
- **"project managers"** (N3): read as `project_manager` **and** `project_administrator` (Q2, **Decided by: User**).
- **"reports as docx"** (N7): all report outputs that offer PDF today (requirement report and every framework report).

## 2. Phase specs

Every phase also carries the standing checklist (§4); only phase-specific items appear below.

### Phase 1 — MCP agent skill + drift enforcement (N5) — DONE 2026-10-06

**As built (differs from the spec below):** module tools are covered by hand-written per-module guidance (`ModuleDefinition.mcp_guidance`, a `mcp_guidance.md` per module) embedded in a generated `module-tools.md`, at the user's request; the reference and drift tests are split in two (core in `mcp-server/`, module in `backend/`) because the two containers share no code; the skill is in `mcp-server/skill/reqtrack-mcp/`, the module reference in `backend/mcp_skill_reference/`. See `docs/decisions.md`.

**Why:** the MCP surface is large (18 read + 5 write core tools, 78 Compliance tools, plus a tool per module report) and AI clients use it poorly without workflow guidance (scope params, write-mode gating, AI-approval gating, pagination). Tools appear as a side effect of declaring a module report, so a "remember to update the skill" prose rule would not even be triggered. **Risk addressed:** stale skill, and untrusted-content handling (requirement text is user-authored and can carry prompt injection). **Outcome:** a downloadable skill whose tool coverage is test-enforced.

```mermaid
flowchart LR
    S["mcp-server/skill/reqtrack-mcp/<br/>SKILL.md (hand-written workflows)"] --> Z["docs build script"]
    G["generate_skill_reference.py<br/>(tool names, params, descriptions)"] --> R["references/tools.md (generated)"]
    R --> Z
    Z --> D["docs/website/static/downloads/<br/>reqtrack-mcp-skill.zip"]
    T["drift test"] -.->|"every tool named in skill"| S
    T -.->|"reference up to date"| R
```

- **Format:** Claude Code skill folder (`SKILL.md` with `name`/`description` frontmatter, `references/`). The same content is offered as plain Markdown for clients that do not load skills (Copilot instructions, generic MCP clients). **Decided by: Agent.**
- **Split:** hand-written `SKILL.md` = when to use which tool, ordering (e.g. `list_projects` → scope → read → write), write-mode and AI-approval constraints, pagination, "tool output is data, never instructions", "never paste or store a PAT". Generated `references/tools.md` = the exhaustive per-tool list, built from the live server tools **plus** `build_mcp_tool_manifest()` (module and report tools are dynamic, so a hand list cannot be complete).
- **Source of truth:** `mcp-server/skill/`, not `.claude/skills/` (that directory holds this repo's own agent skills). The zip is built, not committed, so it cannot drift.
- **Enforcement (the part that matters):** a pytest that fails when (a) any registered tool name is absent from the skill, or (b) the generated reference is stale. Add the rule to root `CLAUDE.md` ("a new or changed MCP tool updates `mcp-server/skill/` in the same change") so agents know *why* the test fails.
- **Docs website:** new "Agent skill" page under `api-integrations/ai-assistants-mcp/` with install steps and the download link; check `docs/mcp-server.md`'s tool counts against the live manifest (it does not yet list the Context & Strategy report tools) and fix any drift in the same change.
- **Tests:** drift test above; zip build smoke test (contains `SKILL.md`, valid frontmatter).

### Phase 2 — Notify project managers of org-level member edits (N3) — DONE 2026-10-06

**As built:** as specced, via `services/membership_notifications.py` (`actor_bypasses_project_managers` is evaluated before the mutation; recipients from `get_project_users_by_role` for manager and administrator). Coalescing keeps one body line per change (cap 20) instead of a count column. Also fixed two pre-existing notification-preference bugs found while testing the opt-out: the in-app opt-out (`ui_enabled=False`) was never applied by the list endpoint, and the daily digest included types the user had opted out of by email. See `docs/decisions.md`.

**Why:** an org admin (or holder of an org-level grant permission) adding or removing a project member bypasses the project's own managers. A notification is a cheap detective control for privilege changes (SOC 2 access-control policy). **Outcome:** project managers learn of direct membership changes they did not make.

- **Trigger rule (precise):** the actor passed the gate without holding a project manager/administrator role on that project (effective roles, including inherited and group-derived). A project manager editing their own project does not notify. Server admins get no bypass, as today. **Decided by: Agent.**
- **Covered endpoints** (`routers/projects/roles.py`, `groups.py`): direct user grant/revoke, by-email add/invite, direct org-group role grant/revoke, project-group role grant/revoke, and (added after user review, **Decided by: User**) project-group member add/remove and group deletion. **Not covered:** changes to *membership inside an org group* (the intended mechanism, per the note).
- **Recipients:** effective `project_manager` holders (resolved through `get_effective_project_members_with_provenance`, so inherited managers count), minus the actor. No managers → no recipients; the existing audit event still records it.
- **Content:** actor, target, role, add/remove, project link. New `NotificationType.PROJECT_MEMBERS_CHANGED_BY_ORG` (notification types are core by design) with a label added to its label map and the preferences page at the same time.
- **Coalescing (pushback):** the add-members flow can issue one request per user, which would send a manager N notifications. Merge into an existing unread notification of the same type, project and actor created within 10 minutes (update its body with a count) instead of creating another. **Decided by: Agent.**
- **Project nesting check:** no new project-scoped definition table; not applicable.
- **Tests:** org admin triggers, project manager does not; each covered endpoint; group-internal change does not; inherited manager receives it; actor excluded; coalescing; preference opt-out; no cross-project leakage of recipients.

### Phase 3 — Request-rate and DB read/write metrics (N2) — DONE 2026-10-06

**As built:** as specced, minus the optional `db_rows_written_total` (`rowcount` is unreliable for batched inserts). Also corrected the "pre-wired dashboards" claim on the docs site and the system-operations policy, not only `docs/deployment.md`. See `docs/decisions.md`.

**Why:** capacity and anomaly visibility (system operations policy). **Outcome:** both figures exposed as Prometheus metrics and documented with ready-to-paste queries. **Decided by: User** (Q6): counters only, no bundled dashboard.

- **API requests per minute:** already derivable: `sum(rate(http_requests_total[1m])) * 60`. No backend change. Multi-worker aggregation is already handled (`PROMETHEUS_MULTIPROC_DIR` in `routers/health.py`).
- **DB reads/writes:** new counter `db_statements_total{operation="select|insert|update|delete|other"}` incremented from SQLAlchemy `before_cursor_execute`, classified from the compiled statement type (not regex on SQL text, which mislabels `WITH … INSERT`). Labels are the operation only; **never** table names, ids or SQL (bounded cardinality, no Restricted data on the unauthenticated `/metrics`). Optional second counter `db_rows_written_total` from `cursor.rowcount`. 15-minute figures are `increase(db_statements_total[15m])`.
- **Docs instead of a dashboard:** add the exact PromQL for requests/min and DB reads/writes per 15 min to the observability docs (website and `docs/deployment.md`). Also correct `docs/deployment.md`, which says the README documents "pre-wired dashboards"; none exist (Prometheus scrape config only).
- **Not doing:** a provisioned Grafana dashboard and `postgres_exporter` (Q6).
- **Tests:** counter increments by operation for a known request; no table/SQL in label values; `/metrics` still renders under multiproc mode. Update `docs/solution-architecture.md`'s "Required metrics".

### Phase 4 — Personal project-nav ordering (N4) — DONE 2026-10-06

**As built:** as specced, in `components/ProjectNavSection.tsx`, `ProjectNavEditor.tsx` and `navigation/projectNav.ts`. Differences: `NavRailLink` moved to its own file; `AuthContext` gained a batch `setUiPreferences` (separate concurrent PATCHes are read-modify-write on one bag); `null` now deletes a preference key; "More" is an inline disclosure when expanded and a Popover when icon-only, where "Customise navigation" becomes its own row (the section label collapses to a divider there); pinned items can still be reordered, only not moved to More; stale-override pruning is client-side and best effort. See `docs/decisions.md`.

**Why:** users use different parts of the product; a fixed order forces scrolling. **Outcome:** each user orders the Project nav section and moves rarely used items behind "More"; stored with the account, so it follows them across devices.

- **Refactor first:** `Layout.tsx` hard-codes nine core `NavRailLink`s, then module entries from manifests. Replace with one `ProjectNavItem[]` model (`key`, label, icon, path); core keys are fixed strings, module keys are `<module_key>:<nav_path>`. Core code stays module-agnostic (module-boundary rule: it consumes the existing manifest generically).
- **Storage (Q3, Decided by: User: per user with per-project override):** `ui_preferences["project_nav"] = { order, more }` is the user's default for every project; `ui_preferences["project_nav:<project_id>"]` optionally overrides it for one project. Resolution: project override if present, else the user default, else the product default. Unknown keys are ignored; new items (newly enabled module) fall into default position, so nothing silently disappears. The editor shows a "Use for all projects / Only this project" choice and a "Remove override" action; per-project keys are removed when empty. Override keys count against the `ui_preferences` bounds below, so stale entries for deleted projects are pruned when the editor saves.
- **"Hide" = "More":** items in `more` render inside a "More" disclosure at the bottom of the section. **Overview** and **Admin** are pinned (not movable into More). The active route's item is always shown, so a user is never stranded on a page whose link is hidden. In icon-only rail mode, "More" is a Popover.
- **Editor:** a Modal ("Customise navigation") launched from the section label, per the style guide. Up/down buttons are the primary reorder control (keyboard- and screen-reader-accessible); drag is optional sugar. "Reset to default". Toast on save.
- **Hardening found:** `ui_preferences` is an unbounded `dict[str, Any]` merge (`schemas/auth.py`, `routers/auth.py`). Add size/shape bounds (max keys, max serialised size) with a test, and widen `useUiPreference` to JSON values. This is a pre-existing gap and is fixed here.
- **Tests:** Playwright (reorder, move to More, persistence after reload, reset, per-project override vs default, active-item-always-visible, collapsed rail); Storybook for the editor and the nav list; unit tests for merge logic (unknown/new keys); backend bound test.

### Phases 5–7 (+5b) — Links everywhere and traceability views (N1)

**Why:** traceability is central to the product, but links are currently buried in per-page cards, and no one can see "where did this come from / what does it touch". **Outcome:** every artefact detail page shows its links beside the content, with a tree and map for multi-hop understanding.

**Facts from the code:** `ArtefactLink` is generic and polymorphic; `get_links_to_many`/`get_links_from_many` support batched traversal; links are validated within a single project today (cross-project is Module 7 Phase 4); module artefacts expose `ArtefactSummaryProvider` (label, status, project, archived) but the two core types (requirement, action) have no provider; the frontend has `getArtefactPath()` for routing. Nine link UIs exist: the requirement detail's inline card, compliance's `RequirementTraceabilityLinksSection`, five `*RelationshipsSection`s in Context & Strategy, Decisions' `DecisionRelationshipsSection` and Stakeholders' `RelationshipsPanel` (also `ArtefactLink`-backed). That is the "fifth one-off" debt the style guide names.

```mermaid
flowchart TD
    UI["ArtefactLinksPanel (core, shared)"] -->|"GET /projects/{pid}/artefacts/{type}/{id}/link-graph<br/>?depth=&direction="| API[Link graph endpoint]
    API --> SVC["services.link_graph<br/>batched BFS, node cap"]
    SVC --> REL[services.relationships]
    SVC --> RES["resolvers: core (requirement, action)<br/>+ registry ArtefactSummaryProvider"]
    SVC --> AUTH["per-node gate: same project/org,<br/>module enabled, read permission"]
    AUTH -->|"denied"| HID["counted as hidden_count,<br/>never traversed through"]
    MCP["MCP tool get_artefact_link_graph"] --> API
```

#### Phase 5 — Link-type direction + backend — DONE 2026-10-06

**As built (differs from the spec below):** the graph needs every linkable type to be displayable, so Phase 5 also added summary providers (`summaries.py`) for all first-party types that lacked one (Strategy, Future State, Guiding Principle, Open Question, Persona, Stakeholder, Stakeholder Need, the three Compliance types), not only core resolvers. The batch hook is `ArtefactSummaryProvider.get_many_in_project(db, project_id, ids)` (the owning module applies its own visibility, e.g. per-project hiding of an org Persona) rather than a plain `get_many`; `ArtefactSummary.project_id` may now be `None` for an org-owned record. Seeded default link types carry a `flow` for new organisations where the direction is unambiguous; existing organisations and module-created types stay `none`. The response also has `unavailable_count` (a type no module can display), separate from `hidden_count`. Migration is `0065` (revision numbers are shared with module migrations; `0058` was taken). See `docs/decisions.md`.

- **Link-type direction (Q7, Decided by: User):** `RequirementLinkTypeDefinition` gains `flow`: `none` (default), `forward_is_upstream` (reading source→target with `forward_name`, the target is a source/origin of the source, e.g. "Derives from") or `forward_is_downstream` (the target depends on or follows from the source, e.g. "Is implemented by"). Symmetric types ("Related to") stay `none`. A migration adds the column defaulting to `none`; existing and seeded types keep their behaviour. The org link-type admin UI gets a labelled select (label map per the enum rule) with a one-line explanation and example. Unconfigured types still appear, in a "Related" bucket, so nothing is hidden, but the upstream/downstream views are only as good as the org's configuration; the docs say so. Untyped structural links (`link_type_id` null, e.g. action membership) have no flow and always land in "Related". Org-scoped table, so the nested-project fallback check does not apply.
- Edges in the graph response carry the resolved `flow` relative to the **root** direction of travel, so the client never re-derives it.
- Endpoint returns `{root, nodes[], edges[], truncated, hidden_count}`; edge carries the link-type forward/reverse phrase and `flow`. `depth` 1–3 (default 2), hard cap 150 nodes (`truncated=true` beyond), `direction=outgoing|incoming|both`.
- **Security (SOC 2 multi-tenant isolation; consult access-control policy):** the service layer does no auth by design, so this endpoint is the authorization point. The root is resolved and authorised like any detail read. Every other node must pass: same organisation and project as the request, owning module enabled, caller holds read on that artefact type (Fine-Grained Access Control). A failing node is excluded, counted in `hidden_count`, and **not traversed through** (otherwise paths would leak the existence of hidden artefacts). Archived nodes are returned flagged, not dropped.
- **Generic resolvers:** add core resolvers for `requirement` and `requirement_action`; add an optional `get_many` to `ArtefactSummaryProvider` to avoid N+1; add a registry-contributed type display label if none exists (a generic extension point, not a per-module edit in core).
- **MCP:** read-only `get_artefact_link_graph`, so AI clients get impact analysis. Phase 1's drift test then requires a skill update.
- **Tests:** flow resolution for forward/reverse traversal of each `flow` value and untyped links; migration default; cross-project/cross-org isolation, disabled module, FGAC-denied node not leaked or traversed, depth/cap/`truncated`, cycles (A→B→A), self-links, symmetric link types, archived nodes, query count stays bounded (≤ 2 link queries per level).

#### Phase 5b — Link authoring coverage (added 2026-10-06 after review)

**Why:** the user asked whether a Pain Point can be linked to a Decision and on to a Requirement. It cannot, and the audit below shows the gap is structural, not one missing option. Phase 6 would otherwise put a shared panel on pages that still have no way to add the links it displays. **Outcome:** any two artefacts that can meaningfully relate can be linked from the UI at either end; every artefact type is covered or explicitly exempt; a test stops a new module shipping an unlinkable type.

**Audit (code read 2026-10-06).** "Add" = can create a link from this page; "Shows" = lists existing links (including incoming); "Panel" = what Phase 6 must deliver.

| Artefact | Detail page | Add | Shows | Gap |
|----------|-------------|-----|-------|-----|
| Requirement | `RequirementDetailPage` | requirement ↔ requirement only; compliance picker tab | req ↔ req, compliance | No module-origin links shown or addable: a Decision that *implements* it, a Pain Point that *motivates* it, a Strategy that *drives* it are invisible from here. |
| Action | `ActionDetailPage` | none | linked requirements (read-only) | No add; no other link types. |
| Pain Point | `PainPointDetailPage` | 5 kinds (Strategy, Requirement, Open Question, Future State, Pain Point) | yes | **No Decision.** |
| Strategy | `StrategyDetailPage` | 5 kinds (+ supersedes) | yes | No Decision, Pain Point or Guiding Principle from this side. |
| Future State | `FutureStateDetailPage` | 3 kinds (+ supersedes) | yes | No Decision, Strategy from this side. |
| Guiding Principle | `GuidingPrincipleDetailPage` | 2 kinds (+ supersedes); fewer at org scope | yes | No Decision, Future State from this side. |
| Open Question | `OpenQuestionDetailPage` | 2 kinds | yes | No Decision. |
| Decision | `DecisionDetailPage` | Requirement (implements/affects), Decision (depends on/conflicts/supersedes) | yes | **No Pain Point, Strategy, Future State, Guiding Principle, Open Question, Compliance.** |
| Persona / Stakeholder | detail pages | 7 relationship kinds | yes | Fine; migrate onto the registry. |
| Stakeholder Need | `NeedDetailPage` | holder panels only | holders only | No generic links. |
| Compliance (3 types) | `ProjectComplianceDetail`, `EvidencePanel` | requirement side only | requirement side only | Own pages show none. |
| Change Request | `ChangeRequestDetailPage` | none | none | Out of scope (no `ArtefactLink` rows; plan §1). |

**Root causes**
1. **Link kinds are hard-coded per source type, in seven places:** five `*_LINK_SPECS` dicts in `context_strategy/service.py`, `RELATIONSHIP_KINDS` in `stakeholders/relationships.py`, two enums in `decisions/service.py`, plus requirement `/links`. Nothing can ask "what can I link this to?", and a pair nobody hard-coded is unlinkable.
2. **Creation is one-directional.** A kind is addable only from its source type's page, so most pairs are unreachable from the other end.
3. **The Decision-target kinds were deliberately reserved** (Module 4 plan, Phase 7: "blocked on Module 1"). Module 1 has since shipped.

**Design — any artefact can link to any artefact; the link type is the constraint (Q10, Decided by: User).**
Link types are already the org-level, admin-managed vocabulary (`RequirementLinkTypeDefinition`, which Phase 5 gave a `flow`). They become the only place a pairing rule lives, and the per-module hard-coded kinds stop being the gate.
- **Default is unrestricted.** Any two registered artefact types in the same project can be linked, provided both owning modules are enabled for the project and the caller passes the authorisation below. A new module's artefact types are linkable the day they register, with no per-module edit.
- **Optional restriction on the link type:** `allowed_source_types` and `allowed_target_types` (nullable; null = any), plain validated strings checked against the registry-merged `get_all_registered_artefact_types()`, the same mechanism as `ArtefactLink.source_type`, never a core enum. Enforced **at link creation only**, in the service layer (the one place every creator, including the legacy typed endpoints and MCP, goes through). Editing a restriction never deletes or invalidates existing links; the panel flags any link that no longer satisfies its type. A restriction naming a type whose module is later uninstalled is tolerated (it simply matches nothing). Reverse reading is implied: a restriction is stated source → target in the forward direction, and the reverse phrase is offered from the target's page.
- **Link-type admin UI** (org link types, where `flow` is already edited): two labelled multi-selects "Can link from" / "Can link to", with "Any artefact" as the empty state, labels from the registry's artefact-type labels (never the raw type string), and a one-line example. This is the only core UI change; the artefact-type choices come from the registry, so no module is named.
- **Modules seed types, they do not gate.** `ModuleDefinition.link_type_seeds` (a generic extension point; core names no module) lets a module declare link types it wants to exist, each with `forward_name`, `reverse_name`, `flow`, and optional source/target restriction. They are created lazily on first use, as the C&S/Decisions code does today, and **only when absent: an org's edited type is never overwritten**. Seeds replace the seven hard-coded vocabularies: the existing per-source specs are re-expressed as seeds, then the old enums/dicts are deleted. Existing typed endpoints keep their URLs and request shapes until Phase 6 retires their UIs. A seed with side effects (*Supersedes* flips a status) is marked `dedicated_endpoint`; the generic add row hides it and the owning page keeps its dedicated action.
- **Untyped links:** the generic endpoint always requires a link type; the seeded symmetric "Related to" (unrestricted, flow `none`) is the default choice in the panel, so "just link these two" is one click.
- **Generic endpoints:** `GET /projects/{pid}/artefacts/{type}/{id}/link-types?other_type=` returns the types usable from this artefact (restriction-filtered, with the correct forward or reverse phrase for the orientation, optionally narrowed to a chosen target type); `POST .../links {link_type_id, direction, other_type, other_id}`; `DELETE .../links/{link_id}`. Authorisation reuses the link-graph gate (project membership, same project, both modules enabled, `view` on the other end) plus *manage* on the **page's own** artefact type through Fine-Grained Access Control, and audits through `services/audit.py` like the existing link creators. SOC 2: consult the access-control policy; record identify → verify → remediate. The link-type dropdown is filtered by the chosen target type, so a restriction is guidance in the UI and a hard rule in the service.
- **MCP:** core tools `list_artefact_link_types`, `create_artefact_link`, `delete_artefact_link` (skill and generated reference updated, enforced by Phase 1's drift test). **Decided by: Agent.**
- **Existing org link types stay unrestricted on migration (Decided by: Agent).** They were de facto requirement ↔ requirement because that was the only UI; under the new design unrestricted is the stated default, and an org that wants the old behaviour sets the restriction. The requirement-to-requirement picker is unaffected (it already chooses both ends).

- **Restrictions from the other side: artefact-type link rules (Q12, Decided by: User).** A link type can say which artefact types it may join (above); an artefact type can also say which link types it may use ("a Requirement may only be linked with *Derives from* and *Implements*"). Model: `ArtefactTypeLinkRule(organization_id, project_id NULL, artefact_type)` with a child table of allowed `link_type_id`s (real FKs, so a deleted type cannot dangle). No rule = any link type. A rule is a closed list and may not be empty (422). Phase 5b ships org-scope rules; Phase 5c adds project scope.
  - **Combined check, at creation, in the same service-layer validator as the link-type restriction:** a link of type T from S to D is allowed iff T's own restriction (if any) permits S → D **and** S's rule (if any) includes T **and** D's rule (if any) includes T. All three must pass, so either side can veto. The rejection message names which rule failed.
  - **Fixed-semantic actions are exempt** (the *Supersedes* flow, legacy typed endpoints until Phase 6 retires them), as with hiding: a lifecycle step is not a user-chosen link. **Decided by: Agent.**
  - Rule entries are validated against the registry-merged artefact types and tolerated when a module is later uninstalled. Enforced at creation only; existing links that no longer comply are flagged in the panel, never deleted.
  - **UI:** a second view in the shared link-type panel, "By artefact type": a row per registered artefact type (label from the registry, never the raw string) with its allowed link types or "Any link type". Editing a rule uses the confirmation and Toast patterns; Playwright and Storybook cover it.
  - Rules narrow what is *offered* in the panel's link-type dropdown too (the dropdown is filtered by both ends' rules), so a restriction is guidance in the UI and a hard rule in the service.
- **Deleting a link type that is in use: a dialog, not a dead-end (Decided by: User).** Today the delete returns 409 with a count and `DefinitionList` shows an inline reassign dropdown. Replace that with one shared `DeleteInUseDialog` (Modal), used by every vocabulary that already routes through `DefinitionList` (statuses, action types, link types, Pain Point types), with the existing call sites updated and the inline row deleted (shared-component rule). It shows how many links use the type (and how many projects, see Phase 5c for what a project admin may see), then offers:
  1. **Move the links to another link type:** a select of candidate types; a candidate that cannot take every affected link (its own restriction, either end's artefact rule, or not usable in every affected project) is shown disabled with the reason, never silently skipped. Warns when the candidate's `flow` differs ("this changes what these links mean", the existing docstring's concern). A moved link that would duplicate an existing link of the target type between the same two records is **merged** into the existing one, and the count is reported in the Toast.
  2. **Delete the links too (link types only; opt-in per vocabulary):** a Tier-2 type-the-name confirmation (style guide: irreversible, wide blast radius), stating the count.
  - **API:** `GET .../link-types/{id}/usage` (link count, project count, pending change requests, approved-requirement count, per-candidate compatibility) and `DELETE ...?mode=reassign&reassign_to_id=` or `?mode=remove_links`. A plain delete of an unused type, and the 409-with-count contract for an in-use one, are unchanged, so other callers do not break. Everything runs in one transaction and writes per-link audit events plus the type event (CLAUDE.md audit rule; a bulk removal must be reconstructable).
  - **Findings fixed here (found while reading the delete path):**
    - `ChangeRequest.proposed_link_type_id` is `ON DELETE SET NULL`. Deleting a type silently strips it from pending `ADD_LINK` change requests, leaving requests that can no longer be applied. *Move* repoints them; *delete links* is **blocked while pending change requests propose the type** (409 with the count) until they are resolved.
    - A type named in an artefact rule: *move* substitutes the replacement into the rule; *delete links* removes it from the rule and is blocked if that would empty a rule (422/409 naming the artefact type), never widening a rule silently.
    - The "an organisation must keep at least one link type" floor must count org-wide types only once project-local types exist.
  - **Bulk removal of links is allowed (Decided by: User, Q13).** It may delete links on approved requirements in projects that require a change request for links: an admin does it behind the Tier-2 confirmation, it is audited per link, and the dialog states how many such links are affected so it is never a surprise.

**Seeded types (Decided by: Agent, revisitable; vocabulary from Module 1 §5.6/§6.6/§7/§8.5/§9.5 and Module 4's reserved list).** Restrictions shown are the seed's defaults and are editable by the org admin.

| Seed (forward / reverse) | From → to | Flow |
|--------------------------|-----------|------|
| Addresses / Is addressed by | Decision → Pain Point | forward is upstream |
| Resolves / Is resolved by | Decision → Open Question | forward is upstream |
| Supports / Is supported by | Decision → Strategy | forward is upstream |
| Guided by / Guides | Decision → Guiding Principle | forward is upstream |
| Constrained by / Constrains | Decision → Compliance requirement | forward is upstream |
| Related to | any → any (already seeded, unrestricted) | none |

Result: *Pain Point —is addressed by→ Decision —implements→ Requirement* works from any of the three pages, and so does any pairing nobody foresaw, via "Related to" or an org-defined type. Pain Point → Requirement (*Motivates*) already exists and is the workaround until this lands. `default flow` is applied only when a seed creates a type, never to an existing one.

**Scope decisions**
- **Org-scoped records** (org Strategy / Future State / Guiding Principle) have no project, and links are project-scoped. Their pages show the panel with a one-line "links are managed from within a project" note rather than an add row. **Decided by: Agent.**
- **Nested projects:** link types are org-scoped and seeds are code declarations, so the nested-project fallback check does not apply (same conclusion as Phase 5).
- **Risk of the user's design, accepted:** unrestricted by default means meaningless pairings are possible ("Duplicate of" between a Persona and a Compliance item) unless an admin restricts the type. Mitigated by the seeds shipping with sensible restrictions and the dropdown filtering by target type.

**Coverage guard (the permanent form of the scan):**
- Backend test: for every pair of registered artefact types, an unrestricted type can link them (both orientations); a restricted type rejects a non-matching pair and accepts a matching one; restrictions naming unregistered or uninstalled types are rejected on write, tolerated on read; the combined check (link-type restriction, source rule, target rule) with each of the three vetoing independently, an empty rule rejected, fixed-semantic actions exempt; a module with an artefact type needs no other edit to be linkable.
- Frontend unit test: every registered artefact type has a `getArtefactPath` route, so a type cannot be linked yet unreachable.
- Playwright "links on every detail page" spec (added with Phase 6's panel, driven by the seeded dataset): each type's detail page shows the Links panel and an add row. The audit matrix above is its fixture.

**Tests:** backend pytest for restriction validation and enforcement (service-level, so legacy endpoints and MCP are covered), generic create/delete (authorisation, cross-project, duplicate, hidden target, audit row, FGAC denial), orientation and phrase selection, seed creation without overwriting an edited type, `dedicated_endpoint` hidden, migration leaves existing types unrestricted, old typed endpoints behave identically; delete-in-use (usage counts; move with incompatible candidates disabled and explained; duplicates merged; remove-links behind type-the-name; pending change requests block removal and are repointed on move; rule substitution and empty-rule block; one transaction with per-link audit events; the unchanged 409 contract for other callers); Playwright for the link-type admin restriction selects, the "By artefact type" rules view, and the delete dialog in both modes (set, clear, label-mapped options); Storybook for the dialog and rules view; Storybook for the new admin fields; seeds gain a Pain Point → Decision → Requirement chain and one restricted type in both datasets; docs: `docs/modules.md` (new `link_type_seeds` field), `docs/solution-architecture.md`, website requirements/modules pages, `docs/decisions.md`.

#### Phase 5c — Project-level link types, and an org switch to forbid them (added 2026-10-06)

**Why:** an org-wide vocabulary suits a product firm that wants every project consistent, but a consultancy running each project independently needs project admins to define their own link types and drop the org ones they never use. Both are legitimate (Q11, **Decided by: User**), so the capability is per-org switchable. **Outcome:** a project admin can add link types for their project and hide org types from its pickers; an org admin can turn that off for the whole org, restoring a single unified vocabulary without deleting anything.

**Design**
- **Project-local types are rows in the existing table.** `RequirementLinkTypeDefinition` gains nullable `project_id` (NULL = org-wide, the current meaning). `ArtefactLink.link_type_id` already points at this table, so `flow`, restrictions (Phase 5b), phrases and every traversal in `link_graph` keep working unchanged. A separate project table (the Pain Point types shape) was rejected: it would need a second reference path from `ArtefactLink` and a reconciliation on deletion, which that module's own decision log calls "materially more complex". **Decided by: Agent.**
- **Visibility is a small table, `ProjectLinkTypeVisibility(project_id, link_type_id, hidden)`, nearest row wins up the project chain.** It applies to any type visible to the project (org-wide or inherited local). A parent's hide therefore carries down to its children, and a child can show it again with its own `hidden=false` row. Rename and re-order overrides of org types are **not** built; nobody asked, and the Pain Point precedent shows they double the surface. **Decided by: Agent.**
- **Hide means "not offered", never "gone":** existing links of a hidden type keep displaying with their phrase; the type disappears from pickers and is rejected by the generic create endpoint and MCP. Fixed-semantic actions (the *Supersedes* flow, the legacy typed endpoints until Phase 6 retires them) are exempt, since the type is intrinsic to the action.
- **Project-scope artefact rules.** Phase 5b's `ArtefactTypeLinkRule` gains project scope here. The **nearest** rule for an artefact type wins (project, then each ancestor, then the org) and **replaces** the farther one entirely, so a consultancy's project can widen as well as narrow, and a product firm that wants unified rules turns the lock on. An org rule can name org-wide types only; a project rule can name any type usable in that project. Same project-admin authority, audit and lock as local types. The panel's "By artefact type" view labels each rule's source with `OverridePill` ("Organisation rule", "Set on this project", "Inherited from <project>") and a one-click "Use inherited rule", per style guide principle 2.
- **One resolver, `resolve_effective_link_types(db, project, source_type=None, target_type=None)`:** org-wide types, plus the local types of the project **and every ancestor** (Q11, **Decided by: User**: child projects inherit), minus whatever the nearest visibility row hides, deduplicated by the ancestor-wins rule, and filtered by the link-type restrictions and both ends' artefact rules when the artefact types are given. The walk is cycle-safe and capped like `resolve_effective_action_types`. Everything that lists types for a user (generic endpoint, panel, MCP, the requirement link picker) calls it; nothing queries the table directly for a picker again.
- **Org switch, as a list of keys, not a bool (Decided by: Agent):** `Organization.project_customisation_locks` is a validated list of keys from one core constant, initially `["link_types"]`. The same consultancy-versus-product-firm choice will recur for action, decision and pain point types, and one column per vocabulary is the thing worth not repeating. Only `link_types` is wired now; **retrofitting the other vocabularies is not part of this phase.** Default is **projects may customise** (the user's wording makes it the capability, with opt-out; **Decided by: Agent** on the default, flip it if you would rather existing orgs opt in).
- **What the lock does:** the project create/hide/delete and project-rule endpoints return 403 with a message naming the org setting; the resolver ignores project-local types, hides and project rules, so the org's vocabulary is exactly what every project sees. **Nothing is deleted**: existing project-local types, hides and rules sit dormant, existing links keep displaying, and unlocking restores them. The org admin's switch shows how many project-local types across how many projects are affected, so the consequence is visible before flipping it.
- **Authorisation:** `project_administrator` (matches Pain Point types), audited through `services/audit.py`. The org switch is org-admin only.
- **Multi-tenant isolation:** see the dedicated section below. It is a first-class part of this phase, not a test footnote.
- **Duplicate names: the ancestor wins (Q12, Decided by: User).** Two types in one project's reach with the same forward name (compared case-insensitively) resolve by precedence: org-wide, then the root-most ancestor, down to the project's own; only the winner is offered, and the other is **shadowed**. A shadowed type is not deleted: links already using it keep resolving and displaying by id, and its owner's panel marks it "Shadowed by <scope>" so they can rename or delete it. Creating a name already provided by the org or an ancestor is rejected up front with that explanation, so shadowing only arises when a parent adds a name a descendant already uses, and the parent's admin learns nothing about the descendant. Uniqueness within one scope stays strict: unique `(organization_id, forward_name)` where `project_id IS NULL`, and `(project_id, forward_name)` where it is not. A rule entry naming a shadowed type is inert.
- **Deleting a type that other projects use: keep it for them by copy (Q13, Decided by: User).** `DeleteInUseDialog` (Phase 5b) gains a third choice when links of the type exist in **child projects** of the owner (or, for an org-wide type, in any project): a checkbox, **default on**, "Keep this link type in the N projects that use it". When ticked:
  - A copy (same forward/reverse names, `flow`, restrictions) is created as a **project-local type in the top-most affected project of each branch**. Descendants below it inherit the copy, so one copy serves a whole branch and no same-named copies fight each other under the ancestor-wins rule. The affected links are repointed to the copy, so they keep their exact meaning.
  - The deleting project's own links, and any links when the box is unticked, follow the chosen move/remove mode as before. The common case is *delete the links here, keep it for the children*.
  - **Authority:** a copy is meaning-preserving (nothing a child sees changes), so it does not need authority over the child: a parent admin can do it for children they cannot manage, and each copy is audited in the child project. Moving or removing links still requires managing every project whose links change; with the box ticked that is only the deleting project, otherwise every affected project, else 409 with a count only.
  - **Name clash** (the target project already has a type of that name): the copy is created as "<name> (copy)" and listed in the Toast, never merged or overwritten. **Decided by: Agent.**
  - **Rules:** an artefact rule that named the deleted type has it removed (blocked if that empties the rule); a copy is **not** added to inherited rules, since a parent's rule cannot name a child's type. A child admin adjusts their own rules if they want the copy offered for an artefact type the inherited rule excludes. Links already made are unaffected.
  - **Offered for org-wide types too** (an org admin deleting an org-wide type used by projects: copy it as a local type into each using project, top-most per branch). **Decided by: Agent**, the same mechanism and consent rule. Disabled with an explanation when the org lock is on, because local types would be dormant.
  - Archived projects are included (their links still display); the dialog counts them.
- **UI (style guide: settings hierarchy depth, platform-default override visibility, create-as-a-layer, confirmation tiers, Toast on every mutation):** the project admin gets a "Link types" panel listing org types as inherited (badge "Organisation", with a Hide/Show toggle) and the project's own as editable, with an "Add link type" action. It is **the same shared component as the org link-type panel** (extract it from `OrgAdminPage`, update that call site, delete the bespoke copy; CLAUDE.md shared-component rule), parameterised by scope, and it shows the same flow and "Can link from/to" fields from Phase 5b. When locked, the panel renders read-only with "Your organisation uses one shared set of link types" and no controls. The org link-type admin gets the switch with the affected-count line.
- **Nested projects (CLAUDE.md checklist, decided at design time; Q11, Decided by: User):** children inherit. Unlike Action Types this is **additive** (own + ancestors' types on top of the always-present org base) rather than "own rows else nearest ancestor's", because a child adding one type should not lose the parent's. Always on, independent of `role_inheritance_mode`/RBAC, like the Action Types fallback. Seeding is not relevant (types are created by admins, not seeded per project). Reparenting or detaching changes what a project can **create** with; links already made keep resolving by id and keep displaying. Record in `docs/decisions.md`. Cross-project links (Module 7 Phase 4) will accept **org-wide types only**, since a type must be usable at both ends.
- **MCP:** `list_artefact_link_types` (Phase 5b) already returns the effective set; no project-type write tool (Decided by: Agent: governance configuration stays a human action).

**Isolation rules (SOC 2 multi-tenant isolation; consult the access-control policy; identify → verify → remediate, recorded in `docs/decisions.md`).**
Today every link type is org-wide, so "is this type in my organisation?" is the whole check, and about twenty call sites rely on it (found by grep for `RequirementLinkTypeDefinition`). A project-local type breaks that assumption: *same organisation* no longer means *usable by, or visible to, this project*. Each place that makes the old assumption becomes a leak or a cross-project reference unless it is changed:

| Where today | What goes wrong with project-local types | Rule |
|-------------|------------------------------------------|------|
| `routers/requirements/links.py` (create), `modules/compliance/.../traceability_links.py`, `routers/change_requests/core.py` (`proposed_link_type_id`) | Accept any type id in the org, so project B's request could name project A's private type | One shared `assert_link_type_usable(db, project, link_type)`: type is in the project's org **and** is org-wide or owned by the project or an ancestor. Every creator, the Phase 5b endpoint and MCP call it. |
| `GET /orgs/{id}/link-types` (any org member may call it) | Would return **every project's** local types to anyone in the org, including people with no access to those projects | Returns org-wide types only. Local types come only from the project-scoped endpoint, behind project membership. |
| Org admin create / rename / move / delete (`routers/orgs/taxonomies.py`) | Name-uniqueness check, `sort_order` count, "never leave the org with zero types" and `move_ordered` all span local rows; rename/delete could reach a project's private type | Scope every one to `project_id IS NULL`. Org admins do not edit project-local types through the org endpoints. |
| `delete_link_type(reassign_to_id=…)` | Reassigning an org-wide type's links to a project-local type would point **other projects'** links at a type they cannot use | `reassign_to_id` must be org-wide. |
| Lazy fetch-or-create in C&S, Decisions, Stakeholders (`select … where organization_id, forward_name`) | A project's local "Addresses" could be picked as the org's | Filter `project_id IS NULL`. |
| `link_graph.py`, `project_export.py`, `requirement_csv.py` (load all org types) | Over-fetch; and a link whose type is no longer usable (locked org, reparented, hidden) must still show its phrase | Resolve phrases **by the ids the visible links reference**, never by "all org types". Display needs no usability check, because the link itself was already authorised. |
| Artefact-type rules (read/write) | An org-level rule endpoint that listed project rules would expose private configuration; a rule naming a type the project cannot use would be unenforceable or leak a type id | Org endpoint returns org-scope rules only; project rules only via the project endpoint behind project admin; a rule may only name types usable in its own scope. |
| Delete-in-use with *move* or *remove* (`reassign_to_id`, link rewrites) | A parent admin could rewrite or delete links in child projects they do not manage; a move target could be unusable in some project | Caller must manage every project whose links change, else 409 with a count; the target must be usable in every affected project and compatible with every affected pair (restrictions and rules). Keep-by-copy is the exception (meaning-preserving, audited in the child). |
| Project import (`apply_project_data`, resolves a type by forward name in the org) | A name could resolve to the wrong scope, or to a type the target project cannot use | Resolve among types usable in the **target** project; an unresolved name behaves as today (skipped with a warning, never remapped to a different meaning). |

Further rules:
- **Reading versus using:** *using* a type (create, picker) requires it to be currently usable; *displaying* a link never does. This is what makes the lock, hiding, reparenting and detach all non-destructive.
- **Direction:** a type is usable in a project and its descendants, never in its ancestors or siblings. A parent's links cannot use a child's type.
- **Inheritance discloses names, deliberately and boundedly:** a child's members see an ancestor's local type *names and phrases*, even if they cannot access the ancestor. This is the same accepted trade-off `resolve_effective_action_types` documents (low-sensitivity metadata, never content or identity of the parent). It is consented to by the parent's managers, because attaching a child requires managing both projects (hierarchy decision 12). The ancestor's name is shown only in the scope label when the viewer can already see that project.
- **Deleting an ancestor's local type that a child uses goes through the dialog's authority rule above** (count only, no project names for callers who cannot see them); `ArtefactLink.link_type_id` has no cascade, so the database refuses a bare delete too.
- **Archived projects** keep their types for display; they stop being offered for new links.
- **Audit:** create, edit, delete, hide/show and the org lock each write an event through `services/audit.py` carrying project and organisation ids.

**Tests:** backend pytest for the resolver (org-wide + own + ancestors' local − hidden; nearest visibility row wins, including a child re-showing a parent's hide; restriction filtering; locked org ignores local types and hides; unlock restores; reparent and detach), isolation, one test per row of the isolation table (project A's type rejected in project B and in A's parent through every creator including change requests; org type list returns org-wide only to a plain member; org admin cannot rename/delete/reorder/reassign-into a local type; lazy seed unaffected by a same-named local type; phrases still resolve for a link whose type is no longer usable; import resolves among usable types; sibling and ancestor cannot use a child's type; cross-org id rejected), constraints (collision with an org-wide or ancestor name rejected up front; a parent adding a name a child already has shadows the child's (ancestor wins, case-insensitive, links still display, no leak to the parent); project rules nearest-wins and replacing, the lock ignoring them; delete-in-use across projects with the authority rule and count-only messages; keep-by-copy: copy placed at the top-most affected project per branch, descendants inherit it, links repointed with identical meaning, name clash gets a suffix, unmanaged child still copied but never moved or removed, org-wide variant, disabled under the lock, copies audited in the child, rules not widened), hidden types rejected by generic create and exempt for *Supersedes*, authorisation (non-admin, member of another project, lock 403 with message), audit rows, migration (`project_id` defaults NULL, existing rows unchanged), org switch validation (unknown key rejected). Playwright: parent admin deletes an in-use type, ticks keep-for-children, the child's links and picker still work and the type is now local to the child; project admin creates a type and uses it in the picker; hides an org type (gone from picker, existing link still shows); org admin locks (project panel read-only, project types disappear from pickers, unlock restores); a non-admin sees no controls. Storybook for the panel in org, project, locked and empty states. Seeds: both datasets get one project-local type and one hidden org type in one project, and the e2e dataset gets a second org with the lock on, and a parent/child pair where the child uses the parent's local type. Docs: website link-types page (both scopes and the lock, with a diagram of the effective-set resolution), `docs/solution-architecture.md`, `docs/decisions.md`, README, the access-control policy's notes if the isolation validator closes a gap.

```mermaid
flowchart TD
    ORG["Org-wide link types"] --> R["resolve_effective_link_types"]
    LOC["Local link types of the project<br/>and every ancestor"] --> R
    HID["Visibility rows, nearest wins<br/>up the project chain"] --> R
    RUL["Artefact-type link rules,<br/>nearest wins"] --> R
    LOCK{"Org lock<br/>link_types?"}
    LOCK -- "locked" --> ORGONLY["Org-wide types only"]
    LOCK -- "unlocked" --> R
    R --> OUT["org-wide + local (own and inherited)<br/>minus hidden and shadowed duplicates,<br/>filtered by type restrictions and both ends' rules"]
    OUT --> USE["Panel, generic endpoint, MCP, requirement picker"]
    ORGONLY --> USE
```

#### Phase 6 — Shared panel and migration

- **New shared pieces:** `ArtefactLinksPanel` (direct links grouped by artefact type, direction phrased by link-type name, status badges; the add row is driven by Phase 5b's `link-types` endpoint (effective types per Phase 5c), not a per-page kind list) and `DetailLayout` with an `aside` slot. **Layout:** right-hand, sticky, collapsible (preference-stored), default open at ≥1280px and stacked below content on narrower viewports. Record "detail page with links aside" as a pattern in `docs/ux-style-guide.md` (the existing `SidePanel` is an overlay for row detail, not a persistent column, so it is not reused).
- **Migrate all nine existing link UIs and every artefact detail page** onto it in the same phase, and delete the bespoke components (CLAUDE.md shared-component rule). Module detail pages are module-owned and import the core panel (allowed direction). The requirement page keeps rendering module-contributed extras through the existing `requirementDetailSections` hook, never a core import. Where a module's UI adds typed-relationship semantics the generic panel cannot express (Stakeholders' relationship kinds), the panel takes a render-prop for the add row rather than the module keeping a parallel list.
- **Every row of Phase 5b's audit matrix gets the panel**, including pages with no link UI today (Action, Stakeholder Need, the three Compliance types) and the Requirement page, which now shows module-origin links (Decisions, Pain Points, Strategies, …) through the panel rather than a `requirementDetailSections` entry. Org-scoped pages show the read-only note from Phase 5b.
- **Tests:** the Phase 5b "links on every detail page" Playwright spec; Playwright for each artefact family (view, add, remove, hidden count message, narrow-viewport stacking); Storybook for panel states (empty, many, truncated, hidden).

#### Phase 7 — Tree and map

- **Trace tree:** three groups, **Upstream** (where it comes from), **Downstream** (what depends on it) and **Related** (flow `none`, untyped, symmetric), expandable to depth 3, lazy-loaded per branch, keyboard navigable. A hop keeps its direction of travel, so an upstream branch only continues through upstream edges. Answers "where does this come from / what depends on it".
- **Map:** read-only SVG, a layered layout, deliberately not force-directed (Q1, Decided by: User), depth ≤ 2, node cap, text alternative via the tree. Hand-built SVG avoids adding a graph library (`mermaid` is present but gives no accessible click-through without loosening its security level). **Decided by: Agent.**
- **Map columns:** upstream on the left, focus node centre, downstream on the right, Related below. Empty-state hint links org admins to the link-type flow setting when most links are unclassified.
- **Tests:** Playwright for tree expand/collapse and navigation; Storybook; a11y checks (addon-a11y) on both views.

### Phase 8 — Decision Management reports (N6)

**Why:** Decisions is the only content module with no reporting; the overview's Module 10 list names decision logs and registers. **Outcome:** reports in the catalogue (UI, PDF, CSV, DOCX after Phase 9, MCP tools) with no new framework code, since `ModuleDefinition.reports` already derives routes, gating, catalogue entries and MCP tools.

| Key | Report | Content | Org-wide |
|-----|--------|---------|----------|
| D1 | Decision register | All decisions: code, title, type, status, date, decision maker, owner, supersedes/superseded-by; filters: status, type, date range, include archived | Org variant deferred (Q8) |
| D2 | Approval ageing | Proposed/under-review decisions by days waiting, overdue and unowned highlighted | Org variant deferred (Q8) |
| D3 | Decision log | Decisions made in a period, with context, chosen option and rationale (the status-meeting view) | No |
| D4 | Rationale coverage | Decisions with no linked requirement or other artefact, and requirements with no linked decision (via `ArtefactLink`) | No |

Report keys D1–D4 are this table's own labels; open decisions in §3 use "Q" to avoid the clash.

- Organisation-wide runs need an `org_role_key`; the Decisions module defines only project-scoped roles (`decision_owner`, `decision_approver`), so org variants would need a new org-scoped module role. Project-only first (Q8, **Decided by: User**).
- No new tables; the nested-project fallback checklist does not apply (no new project-scoped definition table). Reports respect the existing rule that report reads are not audit-logged and collectors never include Restricted data.
- **Tests:** collector per report incl. filters, scope (unreadable project excluded), module-disabled project, PDF/CSV render, catalogue entries, MCP tool presence (Phase 1 test). Update `seed_demo_data.py` so decisions span statuses, ages and links; docs website page for the module's reports.

### Phase 9 — Neutral document model and DOCX export (N7)

**Why:** users edit reports after download. **Risk addressed:** a second renderer drifting from the PDF layout, and malformed-XML crashes on user text. **Outcome:** `?format=docx` for the requirement report and every framework report.

```mermaid
flowchart LR
    RR["Requirement report rows"] --> DOC
    FR["ReportResult (module reports)"] --> DOC["ReportDocument<br/>blocks: heading, markdown, table, image, page break"]
    DOC --> PDF[render_pdf - ReportLab]
    DOC --> DOCX[render_docx - python-docx]
    FR --> CSV[render_csv]
    FR --> JSON[JSON]
```

- **Library:** `python-docx` (MIT, pure Python). Pandoc/LibreOffice are rejected: larger attack surface and an extra binary in the image. **Decided by: Agent.**
- **Editable by design:** real Word heading styles (so a table of contents can be inserted), real tables with header-row shading in the org accent colour, cover page, logo, footer and page numbers from the branding template. Wide tables use a landscape section. No images of text or tables.
- **Shared model:** both renderers consume one `ReportDocument` built from `ReportResult` (already neutral) and from requirement rows (currently built directly into ReportLab flowables). **Moving the requirement PDF onto the model is the risky part**; guard it with the existing requirement-report test files (behaviour must not change, same acceptance guard Phase 12b used). Not doing this means every future layout change is made twice (Q5, **Decided by: User**: do it).
- **Security:** markdown subset reuses the existing restricted markdown-it rules, no HTML passthrough, hyperlinks limited to `http(s)`/`mailto`, images only via the existing tenant-checked `resolve_report_images` bytes; **strip XML-invalid control characters** from every user string (python-docx raises on them, a user-triggerable 500); core properties (title, author = "ReqTrackManager", created) without personal data; no user text in field codes.
- **Plumbing:** `format` literal gains `docx`, content type `application/vnd.openxmlformats-officedocument.wordprocessingml.document`, filename helper in `services/downloads.py`, `ReportExportButton` gains a third option. The MCP tools stay JSON.
- **Tests:** re-open generated files with python-docx and assert headings, table cell values, header shading, footer; control-character and `<script>`/markup strings survive; image tenant isolation; every report in the catalogue exports; manual open in Word recorded in the decision log (automation cannot prove Word fidelity).

### Phase 10 — Per-report-type content across template, project and org tiers (N8)

**Why:** a requirements report and a pain-point report need different introductions and appendices; today intro/chapters/appendices exist at three tiers (organisation default, project, report template) but only the requirement report reads them, and module reports take branding only. **Outcome:** each tier holds separate content per report type, optionally with placeholders. **Decided by: User** (Q4A all three tiers, Q4B placeholders, Q9 ancestor fallback).

```mermaid
flowchart TD
    G["Generating report type K"] --> T1["Template content for K"]
    T1 -->|"empty"| T2["Template 'all reports' content"]
    T2 -->|"empty"| P1["Project content for K"]
    P1 -->|"empty"| P2["Project 'all reports' content"]
    P2 -->|"empty"| A1["Nearest ancestor project: K, then 'all reports'"]
    A1 -->|"empty"| O1["Org default for K, then 'all reports'"]
    O1 -->|"empty"| B["Blank"]
```

- **Data:** one table `ReportContent(scope_type, scope_id, report_key, intro, chapters, appendices)` with `scope_type` in {`template`, `project`, `organization`}, unique on `(scope_type, scope_id, report_key)`; ownership is enforced in the service (the polymorphic id has no FK, the same trade-off `ArtefactLink` accepts, so deletion of a template/project/org must delete its rows explicitly and the org-deletion service is updated). `report_key` is a plain validated string (`"requirements"` or `"<module_key>.<report_key>"`) checked against the registry, **not** an enum, so a module adds report types with no core edit (module-boundary data rule). `report_key = NULL` means "all reports lacking their own row". **Migration** moves `ReportTemplate.intro/chapters/appendices`, `Project.report_intro/report_chapters/report_appendices` and `Organization.default_report_*` into `"requirements"` rows and drops those columns, so there is one store, not four. The requirement report's existing "project summary as intro" fallback is kept for the `requirements` key only.
- **Resolution:** each of intro, chapters and appendices resolves independently (as today), in the order in the diagram: tier first (template, project, ancestors, org), then specific key before "all reports" within a tier. Rationale for tier-first: it preserves today's "template beats project beats org default" meaning.
- **Ancestor fallback (Q9, Decided by: User):** a child project with no content of its own for a type inherits the nearest ancestor's, via the same cycle-safe, capped walk as `resolve_effective_action_types` (`services/project_hierarchy.py`), always on, independent of `role_inheritance_mode`. **This changes behaviour for child projects' requirements reports** (previously project then org only); call it out in the migration notes, docs and decision log. Edit/delete endpoints stay scoped to rows a project owns; only the resolve/read path walks ancestors. The editor shows where each value comes from ("inherited from <project>", "organisation default") using the existing override-visibility pattern (`OverridePill`).
- **Order in a document:** intro, chapters, generated sections, appendices. Applies to PDF and DOCX; JSON and CSV are unaffected and the docs say so.
- **Placeholders (Q4B, Decided by: User):** a fixed allow-list, `{{project_name}}`, `{{report_title}}`, `{{generated_on}}`, `{{organisation}}`, substituted by plain string replacement **before** the Markdown goes through the existing escaping, so substituted values are treated as ordinary user text. Unknown `{{…}}` stays literal text. Explicitly **not** a template engine (Jinja-style engines are a server-side template-injection risk). The editor lists the available placeholders and previews them.
- **Editor surfaces (three, one shared component):** the template editor, Report Setup (project) and the org default settings all use one `ReportContentEditor` with a report-type selector (shared `Tabs`) reusing `ReportChapterListEditor`; the existing per-tier editors are replaced, not duplicated. The list of types comes from a generic org-level report-type listing built from the catalogue, so core never names a module's report.
- **Org bundle (export/import):** `services/org_export.py` already carries the org's branding files (logo, login background) as `files/` entries and re-uploads them on import, but nothing tests it, and its report-template export reads `intro`/`chapters`/`appendices` columns this phase drops. So: (a) export every `ReportContent` row of the org's templates, projects (inside each project's data) and the org tier, keyed by `report_key` and by template/project ref rather than raw ids, and re-create them on import (`import_org_bundle`, and `merge_org_bundle` for project/template rows only, since merge never touches the org profile); (b) any image a content row references travels in `files/` through the existing `import_bundled_file` path; (c) a regression test pins that logo and login-background bytes round-trip through an org export/import. Platform-level `ServerSettings` default logos are deliberately not exported (not org-owned). **Decided by: User** (2026-10-06: branding files go in org exports); the content-row part is **Agent**.
- **Tests:** migration preserves existing content at all three tiers and the project-summary fallback; org bundle round-trips logo, login background and per-type content at all three tiers (merge import leaves the org profile untouched); full resolution chain including key vs "all reports", ancestor walk (cycle, cap, own-row-wins), cross-org rejection; unknown `report_key` rejected; placeholder substitution, unknown placeholder literal, hostile values stay escaped; module report PDF/DOCX include the right chapters; org/project/template deletion removes rows; Playwright for each of the three editors and inherited-value display; `seed_demo_data.py` and `seed_e2e_dataset.py` gain per-type content at each tier.

### Phase 11 — Project Modules tab e2e coverage (N9)

**Why:** the project-admin Modules tab (`/projects/{id}/admin/modules`, `ProjectAdminPage.tsx`) was not visible to a user after a deployment (likely a stale frontend; unconfirmed). The only spec touching it, `module-enablement-overrides.spec.ts`, tests override *behaviour* for Context & Strategy as an **org admin**; nothing asserts the tab appears, lists every registered module, or works for a project manager who is not an org admin. **Risk addressed:** the tab silently missing or empty, or a module absent from it, going unnoticed. **Outcome:** a small spec that fails if the Modules entry or any module row is missing. **Decided by: User** (requested 2026-10-06); scope **Decided by: Agent**.

- **Spec (new, disposable org per the idempotency rule):** (a) as org admin, "Modules" is in the project-admin menu and `/admin/modules` renders one `.module-settings-row` per module returned by `GET /projects/{id}/modules` (compared by name, so a newly registered module is covered without editing the spec); (b) the same as a project-only `project_administrator` who is not an org admin (the endpoint is `require_project_view_or_manage`, a different gate from the org page); (c) a module the org has turned off shows its disabled switch and hint, one the org leaves on shows an enabled switch whose toggle round-trips with a Toast; (d) direct navigation to `/projects/{id}/admin/modules` lands on the tab, not the default group.
- **Backend:** one pytest pinning `GET /projects/{id}/modules` for a project manager (non-org-admin) returning every registered module, and 404/403 for a non-member.
- **Not testable here:** a stale frontend after deployment is an ops matter, not a product regression an e2e run can catch. The nav rail already shows the running version (`GET /api/v1/system/version`), which is how to tell. Not adding cache-busting work without evidence that is the cause.
- **Storybook:** `ProjectAdminPage.stories.tsx` already has Modules-tab stories (from line ~1477); add one for the empty ("No modules are registered") state only if it is missing.

### Phase 12 — Docs website reconciliation (all notes)

**Why:** each phase already updates its own website page (§4), but per-phase edits drift: a later phase renames or supersedes something an earlier page describes, and cross-cutting pages (overview, glossary, sidebar, observability, notifications) are only touched by whichever phase remembered. **Outcome:** `docs/website/` matches the shipped behaviour of every phase on this branch, verified in one closing pass. Runs after Phase 11, once the code is final. **Decided by: User** (requested as a final phase 2026-10-06).

```mermaid
flowchart LR
    A["Branch diff vs main"] --> B["Map each user-visible change to its website page"]
    B --> C{"Page exists and is accurate?"}
    C -->|"no"| D["Create or fix page"]
    C -->|"yes"| E["Record 'checked, no change'"]
    D --> F["Build site, check links and Mermaid"]
    E --> F
```

- **Audit:** list every user-visible change from `git diff main --stat` (UI, API, MCP tools, config, metrics, notification types, report behaviour) against pages in `docs/website/docs/`; the judgement per item follows CLAUDE.md's "Docs Website Maintenance" (internal-only changes need no page).
- **Expected touch points:** `core-features/notifications-and-email.md` (member-edit notification, Phase 2), `ai-assistants-mcp/` (agent skill, link-graph MCP tool), `installation-deployment/observability.md` (PromQL for request rate and DB reads/writes), project navigation and Links panel pages (Phases 4–7), `modules/decision-management-module/` (reports), `core-features/reports-and-export.md` (DOCX, per-type content, placeholders, child-project ancestor fallback behaviour change), plus `sidebars.ts`, `introduction/overview.md` and `reference/glossary.md` for new concepts.
- **Screenshot review (whole site, not only touched pages):** the 65 files in `docs/website/static/img/screenshots/` (and the README copies in `docs/screenshots/`) predate this branch, so any screen the branch changed is stale wherever it appears, including on pages that otherwise need no text edit. Grep every page for each changed screen (the Links panel replacing the nine old link sections on requirement, change-request, decision and module pages; project nav ordering/"More" in the sidebar; report setup and template editors from Phase 10; notification list; Decision reports) and list each stale image in the audit table. Retake them per the site's screenshot standard (`docs/plans/docs-website-plan.md`: 1440-wide viewport, seeded demo dataset, real alt text, one-line caption). There is no capture script, so the audit table is the checklist; new or changed UI also needs the seed data to show it (Phase 6 multi-hop links, Phase 8 decisions), else the shot will look empty.
- **Consistency:** terminology matches the UI label maps; every Mermaid diagram renders; no page describes a superseded state (Phase 10 replaces the old per-tier editors, so pages describing them are rewritten, not appended to).
- **Verification:** `docs/website` builds with no broken-link or Mermaid warnings (warnings are fixed, not suppressed); the audit table (change → page → updated / no change needed) is recorded in `docs/decisions.md`.
- **Tests:** no new product tests; the site build is the gate. Retaken screenshots replace the old files in place (same filename, so page references and README stay valid) and are checked visually before hand-back.

## 3. Decisions (all answered 2026-10-06)

| ID | Question | Answer | Decided by |
|----|----------|--------|------------|
| Q1 | Link views | List + tree + layered map; no force-directed web | User |
| Q2 | N3 recipients | `project_manager` and `project_administrator`; direct user and direct org-group grants; not changes inside an org group | User |
| Q3 | Nav scope | Per user, with per-project override | User |
| Q4A | Content tiers | Template, project and org default all per report type | User |
| Q4B | Placeholders | Yes, small fixed allow-list | User |
| Q5 | Requirement PDF on shared model | Yes, guarded by existing tests | User |
| Q6 | DB metrics | Counters only; no dashboard, no `postgres_exporter` | User |
| Q7 | Link-type direction | Add optional `flow` now | User |
| Q8 | Decision reports | Project-level only first | User |
| Q9 | Child-project content fallback | Nearest ancestor, then org default | User |
| Q10 | Which artefacts can link | Anything to anything by default; a link type may restrict allowed source/target artefact types (2026-10-06) | User |
| Q11 | Project link types | Projects can create link types and hide org ones; child projects inherit their ancestors' local types; an org switch can forbid it all; proper tenant isolation required (2026-10-06) | User |
| Q12 | Artefact-side rules, duplicates, delete-in-use | Artefact types can restrict which link types they use; on duplicate names the ancestor wins; deleting an in-use type opens a dialog to move or remove its links (2026-10-06) | User |
| Q13 | Delete-in-use follow-ups | Deleting a type that child projects use offers to copy it into them; bulk removal of links is allowed (2026-10-06) | User |

## 4. Standing checklist per phase

- Tests: backend pytest for every backend change; Playwright and Storybook for every UI change; tests idempotent and independent; one `pytest` at a time.
- SOC 2: consult the access-control, system-operations and data-classification policies for Phases 2, 3, 5, 9; run identify → verify → remediate and record in `docs/decisions.md`; update policy "Known Gaps" if a gap closes (Phase 4's unbounded `ui_preferences`).
- Seeds: update `seed_demo_data.py` and `seed_e2e_dataset.py` (multi-hop links with configured link-type flow, decisions across statuses, per-type content at each tier incl. a child project, a coalescing scenario).
- Docs: `docs/website/` page per user-visible change (N1–N8 all are), README, `docs/solution-architecture.md` for Phases 3, 5, 9, 10, `docs/modules.md` for the new extension points (summary `get_many`, type labels), decisions log with Decided-by tags.
- Style guide: enum/status values through label maps; confirmation tiers and Toast feedback on every mutation; accessible control names.
- Git: the user commits; work is handed back verified.

## 5. Risks

| Risk | Mitigation |
|------|------------|
| Graph endpoint leaks existence of hidden artefacts | Per-node gate, no traversal through hidden nodes, explicit isolation tests |
| Unrestricted default allows meaningless pairings | Seeds ship restricted; dropdown filters by target type; admin restriction UI; enforced in the service layer |
| Legacy typed endpoints diverge from generic linking during the Phase 5b → 6 overlap | Both go through one service-layer check; old endpoints tested for identical behaviour until Phase 6 deletes their UIs |
| Migrating eight link sections regresses existing flows | Migrate per artefact family behind existing Playwright coverage; delete old sections only after parity |
| Requirement PDF regresses when moved to the document model | Existing four requirement-report test files as acceptance guard |
| DOCX renders differently in Word vs LibreOffice | Manual Word check recorded; semantic structure (styles, real tables) tested, not pixels |
| Notification fatigue | Coalescing; per-type preference opt-out |
| Metrics label cardinality | Operation-only labels, test asserts value set |
