# September 2026 Platform Review — Implementation Plan

This document is the persistent, session-resumable implementation plan for a batch of eight items raised in a single direct human review pass on 2026-09-13 (frontend UX polish, one product/workflow feature, and CI runtime). It follows the same phased, resumable structure as `docs/compliance-module-plan.md` — read cold, by a session with no memory of this conversation.

**If you are starting a session against this plan, read "Status / Resume Here" below first.**

---

## Status / Resume Here

**Last updated:** 2026-09-14 (Phase 8 complete — all 8 phases done).

**Overall progress:** 8 / 8 phases complete. Nothing further is planned under this document; a future review pass would start a new plan doc rather than extend this one.

| # | Phase | Status |
|---|-------|--------|
| 1 | CI runtime reduction (pytest-xdist, Playwright parallelism, Docker layer caching) | [x] Done — see `docs/decisions.md`'s "Platform review 2026-09, Phase 1" entry |
| 2 | Nav-rail collapse/expand toggle — circular, centered on the divider | [x] Done — see `docs/decisions.md`'s "Platform review 2026-09, Phase 2" entry |
| 3 | Tabs vs. buttons — distinct visual language | [x] Done — see `docs/decisions.md`'s "Platform review 2026-09, Phase 3" entry |
| 4 | Subtle colour system — status/type colour coding | [x] Done — see `docs/decisions.md`'s "Platform review 2026-09, Phase 4" entry |
| 5 | Access review page — groups/org "show more" + modals off the action menu | [x] Done — see `docs/decisions.md`'s "Platform review 2026-09, Phase 5" entry |
| 6 | Project members table — groups get their own row (editable role, removable) | [x] Done — see `docs/decisions.md`'s "Platform review 2026-09, Phase 6" entry |
| 7 | Requirement-to-requirement link picker — browse (cascade) + search | [x] Done — see `docs/decisions.md`'s "Platform review 2026-09, Phase 7" entry |
| 8 | Change requests for action removal, and opt-in change requests for link changes on approved requirements | [x] Done — see `docs/decisions.md`'s "Platform review 2026-09, Phase 8" entry |

**Instructions for whoever picks up the next phase:** implement exactly one phase, leave the repo passing its tests and in a clean state, add a `docs/decisions.md` entry (tagged **Decided by: User** or **Decided by: Agent** for every design call per `CLAUDE.md`'s documentation-governance rule), then come back to this file and tick its checkbox and update "Last updated." Do not cascade into the next phase automatically. Where a phase below references a policy doc, consult it before writing code, per `CLAUDE.md`.

---

## Origin

All eight items came from one human-review message, not eight separate requests — the user explicitly chose "one combined staged plan" over splitting UI polish from the product/workflow and CI items (**Decided by: User**), mirroring how `docs/compliance-module-plan.md` and the UX audit → style guide → "UI improvement stage N" pattern have handled prior multi-item review passes in this repo.

Two items were clarified with the user before this plan was drafted:
- Item 7 (link picker): the user's first phrasing ("similar flow to the compliance mapping") doesn't actually transfer — compliance mapping avoids the "many items" problem via three *cascading, narrowly-scoped* `<select>`s (standard → version → requirement), not a search/paginate picker (`frontend/src/modules/compliance/RequirementMappingsModal.tsx`). Corrected with the user, who then specified the actual desired shape: a modal offering **both** a cascading browse (component → category → requirement, mirroring the existing `RequirementTree` grouping) **and** a plain search, as alternative ways to find the target requirement (**Decided by: User**).
- Scope/process (all 8 items): one combined plan doc (**Decided by: User**, over "split UI vs. product/CI" and "no plan doc" alternatives).

---

## Open decisions carried into implementation

- **Phase 1 (CI) requires a test-isolation investigation before any parallelism flag is flipped — Decided by: Agent, pending verification.** This repo's own memory/CLAUDE.md already documents that concurrent pytest invocations wedge the shared test database, and that Playwright specs must not depend on shared mutable seed state. `pytest-xdist` workers inside *one* invocation, and Playwright's `fullyParallel`/multiple `workers`, both raise the same underlying question — concurrent writers against one Postgres instance and one seeded fixture set — just inside a single CI job instead of across two. Phase 1's spec below treats "confirm real per-test/per-worker isolation, then parallelise" as one step, not "flip the flag and see."
- **Phase 8's scope was corrected by the user before implementation — resolved, no longer open.** See `docs/decisions.md`'s "Platform review 2026-09, Phase 8" entry: this was never a pre-approval existence gate on links/actions (the plan's original draft spec) — it's a change-request-only-once-locked gate on *modifying* a requirement's actions (unconditional) and links (opt-in per project, with an org-wide force-with-exception), the direct extension of item 514's existing `ADD_ACTION` mechanism. Both new boolean fields default off (**Decided by: Agent**, matching `Project.allow_member_change_requests`'s existing permissive-default precedent).
- **Phase 4's concrete colour choices and entity-accent scope were proposed and confirmed with the user before implementation — Decided by: User.** See `docs/decisions.md`'s "Platform review 2026-09, Phase 4" entry for the confirmed choices and reasoning; resolved, no longer open.
- **Phase 7's scope was substantially revised during implementation, twice, both by the user — resolved, no longer open.** See `docs/decisions.md`'s "Platform review 2026-09, Phase 7" entry: the compliance-linking half of the original "User note" below turned out to already be shipped (compliance-module-plan.md Phase 34, predating this plan), so this phase became "unify the existing core-to-core and compliance pickers into one modal with three tabs (Search, Requirements, Compliance)," and the compliance module's own long-deferred reverse-direction picker was explicitly ruled out for good rather than deferred again.

---

## Phase 1 — CI runtime reduction

**Problem** (`.github/workflows/ci.yml`, job `backend-and-e2e`, `timeout-minutes: 45`, comment claims "normal runs finish in ~15–20 minutes" but current runs exceed 30): the job is strictly serial end-to-end on a default 2-vCPU `ubuntu-latest` runner —
- `docker compose up -d --build` rebuilds three images (`backend`, `frontend`, `mcp-server`) from scratch every run — no BuildKit layer cache (`cache-from`/`cache-to`), no `actions/cache` for Docker layers.
- Backend pytest (`backend/tests/` + `backend/app/modules/compliance/tests/`, 98 files, ~1075 `def test_` functions) runs single-process — no `pytest-xdist`, no `-n` flag.
- Playwright (`tests/playwright/`, 88 spec files, ~143+ top-level tests) runs with `playwright.config.ts`'s `fullyParallel: false, workers: 1` — every spec file, one at a time, single worker — and CI invokes it as one `docker run`, no `--shard` matrix.

**Step 0 — required before touching any flag:** read `backend/tests/conftest.py` (or wherever the DB fixture lives) and the Playwright global setup/seed script to determine actual isolation:
- Does each pytest test get a transaction-rollback or a truncate-between-tests, and would two tests running *literally concurrently* (not just in different order) on one Postgres instance collide on unique constraints/sequences? If so, xdist needs a per-worker database (the standard pattern: read `PYTEST_XDIST_WORKER` env var, create/migrate a `test_{worker_id}` database at session start, point that worker's engine at it) — not just `-n auto`.
- Do Playwright specs share one seeded dataset that a spec running in parallel with another could mutate out from under it (this repo's own testing rule already requires specs not to depend on another test's mutations, but that rule is about *order* independence, not necessarily safety under *literal concurrency* against the same rows)? If any spec still fails that bar, either fix it (per this repo's standing "fix, don't defer" rule) or scope sharding so that spec's file lands alone in its own shard.

**Then:**
1. Add `pytest-xdist` to backend test dependencies; run with `-n 2` (matching the runner's 2 vCPUs — `-n auto` would just resolve to the same on `ubuntu-latest`) once Step 0's DB-isolation question is resolved.
2. Set `fullyParallel: true` in `tests/playwright/playwright.config.ts` and raise `workers` (start conservatively, e.g. 2, given the 2-vCPU runner and that these are I/O-bound browser tests, not CPU-bound) once Step 0's seed-data question is resolved. Consider CI-level `--shard=1/N` matrix jobs as a second, independent lever if in-job parallelism alone doesn't get under the target — this multiplies infra (N separate `docker compose` stacks) so weigh against the layer-caching win below before reaching for it.
3. Add Docker BuildKit layer caching via GitHub Actions cache (`type=gha` cache-from/cache-to on each image build, or `docker/build-push-action` with `cache-from`/`cache-to`) so `pip install`/`npm ci`/`npm run build` layers survive between runs on unchanged dependency files. This is the lowest-risk item — no concurrency implications — and can land independently/first.
4. Do **not** silently move to a larger (paid) GitHub-hosted runner as a first resort — flag it to the user as an option with a cost implication if steps 1–3 don't get close enough to target, rather than choosing it unilaterally.

**Verification:** the identify → verify → remediate pass this repo's change-management policy calls for on security-sensitive changes doesn't strictly apply here (no auth/RBAC/secrets/audit surface touched), but the equivalent due diligence for *this* change is: run the modified suite 3+ times back-to-back (not just once) to catch intermittent concurrency-induced flakiness before merging, since a flaky-under-parallelism CI is worse than a slow serial one.

---

## Phase 2 — Nav-rail collapse/expand toggle: circular, centered on the divider

**Current state:** `frontend/src/components/Layout.tsx` (`LayoutShell()`, ~L179–193) — the toggle is a plain `<button className="btn">` (icon `PanelLeftOpen`/`PanelLeftClose`, lucide, size 16) sitting inside the `<nav className="nav-rail">`'s own top-right content flow, not on or near the dividing line.

**Change:** move the button out of `.nav-rail`'s normal document flow into its own fixed-position element, a sibling of `.nav-rail`/`.app-content`:
- `position: fixed; left: var(--nav-rail-width); transform: translateX(-50%);` so it straddles the border (update the `left` value with the collapsed/expanded rail width the same way `.app-content`'s margin already does, per `frontend/src/styles/theme.css` L516-521).
- Fixed vertical position (e.g. near `var(--header-height)`, not scrolling with rail content).
- `border-radius: 50%`, fixed equal width/height, `background: var(--color-surface)`, `border: 1px solid var(--color-border)` (reuse existing card/rail tokens — do not invent new ones), `z-index` above both `.nav-rail` (currently `z-index: 10`) and `.app-content`.

Update `docs/ux-style-guide.md` if this changes the documented nav-rail pattern's description.

---

## Phase 3 — Tabs vs. buttons: distinct visual language

**Root cause found during planning:** `frontend/src/components/Tabs.tsx` (~L65) literally reuses `.btn`/`.btn-primary` for the active tab — `className={\`btn ${active === tb.key ? "btn-primary" : ""}\`}`. An active tab and a primary button are pixel-identical (same fill, same border-radius, same padding) because they share the same CSS classes, not just similar tokens — this is the exact cause of the user's "tabs and buttons look the same" observation, not a coincidental similarity.

**Change:** give `Tabs` its own visual language, distinct from `.btn`: e.g. a bottom-border/underline indicator on the active tab using `--color-primary`, no filled background, normal-weight surrounding chrome — rather than a solid filled pill matching button styling. Update `docs/ux-style-guide.md`'s "Pattern: Tabs" section (if one exists) to state the rule explicitly, the same way Principle 12 exists so a future page doesn't reach for `.btn` classes on a tab again.

Sequence this phase together with (immediately before or after) Phase 4 — both touch `theme.css` and are easier to review as one coherent pass than as two overlapping diffs.

---

## Phase 4 — Subtle colour system

**Current state** (`frontend/src/styles/theme.css`, documented in `docs/ux-style-guide.md`'s "Tokens" section, ~L510-528): the palette is genuinely "graphite" — almost every token (`--color-bg`, `--color-surface`, `--color-surface-alt`, `--color-border`, `--color-text`, `--color-primary`) is a grey/slate shade. Only `--color-accent` (moss green, used sparingly), `--color-danger` (red), and `--color-warning` (amber) are non-neutral. Status badges render through a single uniform `.badge` class with no colour variation at all — `docs/ux-audit-2026-08.md` already flags this ("status filters show raw enum values") as a separate but related gap. There is a thin real precedent for meaning-carrying colour (`ApplicabilityBadge.tsx` uses `--color-warning`; `.notification-count-badge` uses a hardcoded red), just not applied to status/type generally.

**Proposal (first pass, needs the user's sign-off on specifics before implementing):** the user's own examples (Azure DevOps: colour *per work-item type*; VSCode: colour as a state/change indicator) suggest two independent, additive uses of colour, not one:
1. **Status colour**, wired through the *existing* label-map pattern this repo already requires (`CLAUDE.md`: "any enum/status rendered to a user... must go through its existing label map"). Add a parallel colour map next to `REQUIREMENT_STATUS_LABEL` / `CHANGE_REQUEST_STATUS_LABEL` in `frontend/src/api/types.ts` (e.g. `draft`/`in_review` = neutral/`--color-text-muted`, `approved` = `--color-accent`, a rejected/failed-review outcome = `--color-danger`), consumed by `.badge` via a modifier class rather than inline styles, so a new enum value added later fails loudly (missing colour) rather than silently rendering unstyled.
2. **A small, consistent entity-type accent** (e.g. a coloured left-border stripe or icon tint used consistently on list rows/badges for Requirement vs. Action vs. Change Request vs. Compliance entities) — this is the closer analogue to Azure DevOps's per-type colouring, and is genuinely new (no existing precedent), so it needs the most explicit confirmation from the user before implementation, including exact colour choices.

Both should stay additive to the existing near-neutral palette (a handful of new tokens, not a repaint) to preserve the graphite identity the user said they still like.

---

## Phase 5 — Access review page: groups/orgs "show more" + action-menu modals

**Current state:** `frontend/src/pages/ServerManagementPage.tsx`, `AccessReviewTab()` (~L43):
- Groups column (~L279-282) joins **every** group name into one unconditional inline string — the literal cause of the reported very-long-groups-list for a heavily-e2e-tested user.
- Organisations column (~L271-278) does the same, usually shorter but with the same unbounded shape.
- An `ActionMenu` (kebab) already exists per row (~L304-324) but is currently gated to rows where `!u.has_org_membership`, holding only Deactivate/Reactivate and Ban/Unban.
- "Assign server role" is currently an always-visible inline `MultiSelectDropdown` in the row (~L244-267), not behind any menu.

**Change:**
1. Groups: replace the inline joined string with a compact summary (e.g. first 1-2 names + count), with the full list shown in a modal opened from that row's action menu ("View groups").
2. Organisations: per the user's specific ask, keep them inline but add a "show more" once a user belongs to more than 2 orgs, rather than moving to a modal outright (orgs are typically far fewer than groups) — **Decided by: User**, from "if a user is in say more than 2 orgs... small show more button."
3. Server role assignment: move the inline `MultiSelectDropdown` behind an action-menu modal ("Assign server roles") — **Decided by: User**, on the reasoning given ("not something that is going to be a very common occurrence"). Remove the `has_org_membership` gate on the `ActionMenu` itself if these new actions should be available regardless of org membership (check whether that gate was protecting something specific to the existing Deactivate/Ban actions before removing it wholesale).
4. Preserve the existing `ConfirmDialog`-gated grant/revoke behaviour for server roles inside the new modal — don't drop the confirmation step when relocating it.

---

## Phase 6 — Project members table: groups get their own row

**Current state:** a project member genuinely can be an org Group today via `OrgGroupProjectRole` (`backend/app/models/project.py` L362) — a real, first-class grant, not a UI omission at the data layer. But `frontend/src/components/ProjectMembersTable.tsx` (`ProjectMembersTable()`, L162) only ever renders one row per **user** (`Row = {kind:"member"|"invited", ...}`, L122) — a group's effect is merged invisibly into each individual member's row as a "via org group X" text line (`sourceLine()`, L129), with that role shown checked-but-disabled. **There is no row for the group itself.** The backend revoke endpoint already exists (`DELETE /{project_id}/group-roles/{org_group_id}/{role}`, `revoke_group_project_role`, `backend/app/routers/projects.py` L3410) but has zero frontend callers — confirming the user's "I can't see a way to remove a group" is a real gap, not a discoverability problem.

**Change:**
1. Extend `Row` to a third kind, `{kind: "group", groupRole: OrgGroupProjectRole-shaped data}`, and render one row per distinct group holding a role on the project (alongside the existing user/invited rows, not replacing them).
2. That row's Role column becomes editable directly (unlike today's disabled-checked state on individual members) — wire it to the existing `POST .../group-roles` (add a role) and the currently-unused `DELETE .../group-roles/{org_group_id}/{role}` (remove one), mirroring `UserProjectRole`'s own add/remove pattern in the same table.
3. Add a "Remove group" action (mirroring the existing per-user "Remove all access" `ActionMenu` entry, `ProjectMembersTable.tsx` ~L412) that revokes every role the group holds on the project, gated behind the same `ConfirmDialog` pattern.
4. **Required check, not optional:** verify `assign_group_project_role`/`revoke_group_project_role` (`backend/app/routers/projects.py` L2914, L3410) already emit an audit-log entry via `backend/app/services/audit.py`, the same way individual `UserProjectRole` grants/revokes do. If they don't, that is a pre-existing gap against `docs/soc2/policies/access-control-policy.md` (an authorization-mutation with no audit trail) — fix it in this same phase per this repo's standing "fix, don't defer" rule, don't file it separately.
5. Consult `docs/soc2/policies/access-control-policy.md` before starting, per `CLAUDE.md`'s standing rule for anything touching authorization/RBAC.

---

## Phase 7 — Requirement-to-requirement link picker [DONE — see `docs/decisions.md`'s "Platform review 2026-09, Phase 7" entry for the definitive account]

**Original ask, and two corrections found during planning (kept here for the historical record — the "Change" below is what actually shipped):** the original text claimed `RequirementTree` (compliance module) "already demonstrates grouping by that same component → category structure" as precedent for a browse tab — it doesn't; that component is the compliance module's own standard-requirement hierarchy editor, unrelated to core component/category. It also carried a "User note" asking that compliance requirements be linkable too, "ideally using the same tree" — that turned out to already be shipped (`docs/compliance-module-plan.md` Phase 34, predating this plan), just as a second, separate control below the core Links list rather than integrated into this picker.

**Change (as actually shipped):** one shared `RequirementLinkPickerModal` with three tabs — **Search** (plain text filter), **Requirements** (cascading component → category → requirement browse, built fresh mirroring `RequirementsPage.tsx`'s own create-form cascade, since no reusable tree component existed), and **Compliance** (the compliance module's pre-existing standard → version → requirement cascade, relocated here from its old separate button/`Popover` via a new `requirementLinkPickerTabs` module extension point — contributed only when that module is enabled, core has no knowledge of what a "compliance requirement" is). Single-select add-one-at-a-time semantics, matching the original ask. The compliance module's own long-deferred "initiate from the compliance-requirement side" follow-up was explicitly ruled out for good during this phase, not just deferred again — see the decisions.md entry for the user's reasoning.

---

## Phase 8 — Change requests for action removal, and opt-in change requests for link changes on approved requirements [DONE — see `docs/decisions.md`'s "Platform review 2026-09, Phase 8" entry for the definitive account]

**Original ask, and the correction the user gave before implementation (kept here for the historical record — the "Change" below is what actually shipped):** the section above originally specced a pre-approval *existence* gate — a project could require a requirement to already have at least one link/action before it could be approved at all. The user corrected this directly (quoted in full in the decisions.md entry): this was never about requiring a link/action to exist before approval. It's about *modification* — once a requirement is approved, changing its actions or links must go through a change request instead of the direct endpoint, the same change-request-only-once-locked rule item 514 (2026-08) already established for adding an action. The three approve-path code paths this section originally analysed (`approve_requirement`, `update_requirement`'s approve-path, `create_baseline_for_stage`) turned out to be irrelevant to the corrected scope — nothing gates *approval itself* in the shipped design, only add/remove of actions and (opt-in) links on a requirement that is *already* approved.

**Change (as actually shipped) — two independent gates:**
1. **Actions: unconditional, every project, no toggle.** `unlink_action` (`DELETE .../actions/{action_id}`) had no lock check at all, an asymmetry with `link_action`/`create_and_link_action`'s existing item-514 gate on the *add* side. Fixed by adding the identical `is_locked()` check, routed through a new `REMOVE_ACTION` change-request kind mirroring `ADD_ACTION`'s existing submit → display → apply-on-approval round trip.
2. **Links: opt-in per project, with an org-wide force-with-exception — the mechanism the user's note asked for ("an org admin can override this... unless the project is added as an exception").** `Project.require_change_request_for_approved_links` (default off — links stay ungated by default, matching `RequirementLink`'s own existing "traceability metadata isn't C-G-12 content" design); `Organization.force_require_change_request_for_approved_links` (default off) forces this on for every project in the org except one individually marked `Project.exempt_from_org_link_lock`. `create_link`/`delete_link` are gated by `is_locked() && requires_change_request_for_links()` the same way, routed through new `ADD_LINK`/`REMOVE_LINK` change-request kinds.

See `docs/decisions.md`'s "Platform review 2026-09, Phase 8" entry for the full file list, the SOC 2/access-control identify → verify → remediate review, and complete test/verification results.