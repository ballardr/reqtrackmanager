# Module 12 — Fine-Grained Access Control (Custom Roles & Permissions) — Implementation Plan

See [future-modules-2026-09-index.md](future-modules-2026-09-index.md) for
cross-cutting architecture referenced throughout, including the existing
role-resolution model this plan extends rather than replaces.

**Source:** not from `future-modules-2026-09-overview.md` — requested
directly by the user 2026-09-21, arising out of a Decision Management
(Module 4) discussion about restricting who can approve which Decision
Type. The user explicitly asked for this to be tracked as its own numbered
module rather than folded into Decision Management or Module 8
(Governance) — the right call; see "Why this is not another module's
problem" below. It is also not an invention from nothing: `backend/app/
models/enums.py`'s own module docstring already flags it directly —
*"Ossa (v1) intentionally uses a small, fixed set of organisation and
project roles rather than a customisable permission system (customisable
roles/attributes are a Pelion (v2) concern per docs/requirements.md)"* —
and `docs/requirements.md`'s C-U-01/C-U-03 both describe the existing
fixed roles as a **minimum** ("Organisations must have **at minimum** the
permission roles of...") rather than a ceiling, leaving room for exactly
this kind of additive extension without contradicting the requirements
document this plan cannot itself edit.

**This is a security-sensitive plan.** It touches authorization directly,
so per `CLAUDE.md`'s policy-consultation rule,
[docs/soc2/policies/access-control-policy.md](../soc2/policies/access-control-policy.md)
was read in full before any of this was drafted, not after. That policy's
governing principles for every existing scope (server admin, org role,
project role, module-contributed roles) are: (1) **tenant isolation** —
every check resolves from the *specific* org/project ID in the request,
never "has this role anywhere"; (2) **composition, not replacement** — a
broader existing tier (server admin, org admin, project manager) continues
to satisfy a narrower check without a separate grant, the same way
`require_module_role` already treats `ORG_ADMIN`/`PROJECT_MANAGER` as
implying any org-/project-scoped module role; (3) **no self-escalation** —
a role can never grant itself or a broader one (`MODULE_ADMINISTRATOR` can
only be granted by a full server admin, never by another
`MODULE_ADMINISTRATOR`). This module's entire design is graded against
those three principles, not invented independently of them — see "Design
principles carried over" below.

**Status:** Proposed. Not started. No other module in this roadmap
depends on this one; it is an optional, cross-cutting capability that
*enriches* authorization everywhere else in the product (existing
functionality and every future module's own roles) rather than being a
prerequisite for anything. It can be built at any point, independently of
build order elsewhere in this roadmap — same shape as Module 11.

## Why this is not another module's problem

- **Not Decision Management's problem.** Module 4's Phase 0 addendum
  already considered and explicitly rejected building per-Decision-Type
  approver assignment inside `decisions/` — "Decided by: Agent... avoids
  building a bespoke policy engine here that the future Governance module
  will likely replace outright." Adding it now, narrowly, inside Decision
  Management would repeat exactly the mistake that decision already
  avoided once. The right layer is a general mechanism every module (not
  just Decisions) can consume.
- **Not (only) Module 8 (Governance)'s problem.** Governance's own Phase 2
  ("Approval policies... policies reference roles, never individual
  people") already assumes an existing, fixed vocabulary of roles to
  reference — it configures **which role** approves what per artefact
  type, generically across modules. It does not let an organisation
  **define a new role** at all, fine-grained or otherwise; `role` there
  still means "one of the roles some module happens to have declared in
  Python." This module supplies the thing Governance's own policies would
  then be able to reference: an organisation-definable role, composed from
  atomic permissions, sitting in the same "role" vocabulary a Governance
  policy already points at. The two modules are complementary, not
  competing — see Phase 5's soft dependency note.
- **Not Module 0's problem**, for the same reason Module 11 wasn't: Module
  0 is deliberately scoped to policy-neutral data plumbing with no
  authorization implications of its own. Bundling an authorization
  redesign into it would force security review onto every module riding
  on Module 0, or let this slip through under Module 0's lighter framing.

## Design principles carried over from the existing model (non-negotiable, not open questions)

These are not Phase 0 discussion points — they are established, tested
invariants this plan must not weaken, restated here because they will be
consulted at every phase below:

1. **Additive, never a replacement.** `OrgRole`/`ProjectRole` and every
   existing module-contributed role stay exactly as they are, for every
   organisation that never touches this module. An organisation that opts
   into custom roles gets *additional* ways to grant capability; it can
   never lose the fixed roles as a fallback, and this module ships no
   migration that force-converts an org onto custom roles.
2. **Tenant isolation.** A custom role is defined within one organisation
   and is resolvable only within that organisation's own projects — never
   referenceable from, or leaking into, another organisation, mirroring
   `access-control-policy.md`'s item 2 and the existing cross-project
   mechanisms' own "same organisation only" constraint.
3. **Composition with existing tiers, not a parallel universe.** A server
   admin continues to pass every check. Within an organisation, `ORG_ADMIN`
   continues to satisfy any org-scoped permission check; within a project,
   `PROJECT_MANAGER` continues to satisfy any project-scoped one — the same
   "a higher tier already retains full access" rule `require_module_role`
   already implements for module roles, extended to this new permission
   vocabulary rather than reinvented for it.
4. **No self-escalation.** Only an existing sufficiently-privileged role
   (recommend: `ORG_ADMIN`, resolved per Phase 0 Q5) may create, edit, or
   grant a custom role — never a custom role holder self-granting a
   broader one, mirroring `MODULE_ADMINISTRATOR`'s own grant restriction.
5. **A new, clearly-scoped resolution path, not a rewrite of the existing
   one.** `get_effective_org_roles`/`get_effective_project_roles`'s
   existing 8-source resolution algorithm is already the most complex part
   of `rbac.py` and is exercised by dozens of call sites; this module adds
   a **parallel** `get_effective_permissions` function (Phase 2) rather
   than threading a new concept through the existing one, the same way
   module-contributed roles resolve independently of the core
   org/project-group hierarchy today (documented explicitly in
   `access-control-policy.md`'s role-resolution diagram note).

## Status / Resume Here

0 / 7 phases complete. Phase 0 is next.

| # | Phase | Status |
|---|-------|--------|
| 0 | Exploratory: permission-atom shape & open questions | [ ] Not started |
| 1 | Data model: permission atoms, `CustomRoleDefinition`, grants | [ ] Not started |
| 2 | Effective-permission resolution + `require_permission` | [ ] Not started |
| 3 | Backend API + frontend UI: custom-role management | [ ] Not started |
| 4 | First real consumer migration (proof against a live surface) | [ ] Not started |
| 5 | Decision Management: per-decision-type approver binding | [ ] Not started |
| 6 | SOC 2 policy update + identify→verify→remediate review | [ ] Not started |
| 7 | Docs website coverage | [ ] Not started — depends on Phase 3 |

## Phase 0 — Exploratory: Requirements Clarification & Design Validation

**Why this phase carries unusual weight:** like Module 11, this plan has a
real security posture attached to its central design choice, not just an
implementation-cost trade-off — getting the permission-atom granularity or
the composition rule wrong is the kind of mistake that needs catching
before it ships, not after an audit.

### Open questions for Phase 0

1. **What is a permission atom?** Two real options:
   - **(a) `(artefact_type, level)` pairs — recommended.** Reuse the
     overview's own §4 "Common Role and Permission Model" four-tier
     taxonomy (View / Propose-Create / Manage / Approve-Baseline) crossed
     with every artefact type already registered via `app.modules.
     registry.get_all_registered_artefact_types()` (the same merged
     core-plus-every-module set `services.relationships.create_link`
     already validates against — reused, not reinvented), plus a small,
     hand-maintained list of non-artefact administrative permissions
     (manage members, manage settings, manage integrations, manage custom
     roles itself). A module contributing a new artefact type
     automatically contributes four new permission atoms with zero code
     in this module — the same "extensible without a core-file edit"
     property `artefact_types` already has for the relationship model.
   - **(b) Fully granular, per-action atoms** (e.g.
     `requirement.reassign_creator`, `decision.supersede`). Materially
     finer control (the `creator_id`-reassignment precedent in
     `routers/requirements.py` shows real per-field permission
     differences already exist informally), but a large, hand-authored,
     ever-growing enumeration with no natural registry to derive it from,
     and a mismatch with how this codebase already organises checks
     (small role sets, not per-action ACLs). Recommend deferring this to
     a later phase, if ever needed, rather than building it up front —
     (a) already satisfies the user's stated ask ("group certain
     permissions to create a role").
2. **Does a custom role's scope work like `ModuleRoleDefinition.scope`
   (org/project/module-owned-entity), or is it simpler?** Recommend
   reusing the exact same `scope` concept (a string; `"org"`/`"project"`
   today, extensible the same way) rather than inventing a second scope
   model alongside the one that already exists.
3. **Does a custom role need per-artefact-type scoping within a
   permission** (e.g. "Manage decisions of type Architecture" rather than
   "Manage decisions"), or is `(artefact_type, level)` granular enough,
   with per-decision-type restriction left to Phase 5's own, narrower
   mechanism? Recommend the latter — keep this module's own permission
   atoms at the artefact-type level; type-level-within-an-artefact-type
   restriction is Phase 5's problem specifically because it is a Decision
   Management (and, later, Governance) concern about *which artefact
   instances a role applies to*, not a general permission-atom concern.
   Conflating the two risks a combinatorial permission-atom explosion
   (artefact type × level × every module's own sub-type vocabulary).
4. **Can a custom role compose with module-contributed roles, or only
   with core permissions?** Recommend: every module-contributed role
   (Decision Owner, Compliance Officer, etc.) is *also* expressed as a
   set of permission atoms at declaration time (a new, optional field on
   `ModuleRoleDefinition`, additive and defaulted to empty for any module
   that doesn't opt in), so a custom role can be built from the union of
   core-plus-every-enabled-module's atoms in one picker — this is what
   actually satisfies "group certain permissions... similar to Azure"
   across the whole application, not just core artefacts.
5. **Who can create/manage custom roles?** Recommend `ORG_ADMIN` only —
   matching who already manages every other org-scoped grant surface
   (module role assignment, org groups, SSO mappings) and avoiding a
   bootstrapping problem (a custom role couldn't plausibly be trusted to
   grant itself the right to create more custom roles).
6. **Does a custom role grant require the granting admin to already hold
   every permission in it** (a "you can't hand out what you don't have"
   rule), or can an `ORG_ADMIN` grant any custom role regardless (since
   `ORG_ADMIN` already implies every org-scoped permission per principle
   3 above)? Recommend the latter for v1 — `ORG_ADMIN` already implies
   everything at org scope, so the question only has teeth once/if a
   narrower "can manage custom roles" permission is delegated away from
   `ORG_ADMIN` itself, which this plan does not propose doing.
7. **Grant surface: direct grant only, or also group grants (mirroring
   `GroupModuleRole`)?** Recommend building both from the start, in one
   pair of tables shaped exactly like `UserModuleRole`/`GroupModuleRole`
   — the group-grant path was a deliberate, user-requested reversal
   (module system Phase 30) after v1 shipped without it once already;
   avoid repeating that sequence here when the shape to copy already
   exists.
8. **Frontend surface.** A new org-settings "Custom Roles" page: a
   permission-atom picker (grouped by artefact type/module, matching how
   `OrgAdminPage.tsx` already renders module roles by server-provided name
   rather than a frontend-known enum — see research finding on
   `types.ts:463`'s existing "render `name` directly" precedent), a
   name/description field, and save; assignment reuses the existing
   member-role `MultiSelectDropdown` the same way module roles already
   slot into it. Confirm this is the right home before Phase 3, per the
   UX style guide's settings-hierarchy-depth model.
9. **Naming.** "Custom Roles," "Permission Sets," or something else, for
   what the UI calls this? Cosmetic, but worth settling once rather than
   drifting across phases — recommend "Custom Roles" (matches the mental
   model: still a role, just one an org built instead of one this codebase
   shipped).

**Exit criteria:** user sign-off on Q1–Q9 above, in particular the
permission-atom shape (Q1) and the scope model (Q2), before Phase 1 starts.

## Phase 1 — Data model: permission atoms, `CustomRoleDefinition`, grants

**Scope** (assuming Phase 0 resolves toward the recommended options):

- No new enum of permission atoms as a giant hand-maintained list — a
  `Permission` is derived data: `(artefact_type, level)` for every
  registered artefact type × the four levels, plus a short, explicit list
  of non-artefact administrative permissions declared directly in this
  module. A registry function, `get_all_permissions()`, mirrors
  `get_all_registered_artefact_types()`'s own shape.
- `CustomRoleDefinition` — org-scoped (`organization_id` FK), `name`,
  `description`, `scope` (per Phase 0 Q2), and a `CustomRolePermission`
  join table (`custom_role_id`, `permission` string) rather than an array
  column, so individual permission grants stay independently queryable
  and diffable — the same normalised-join-table precedent this codebase
  already uses everywhere else (never a serialized array/JSON blob for a
  set that needs per-row operations).
- `UserCustomRoleGrant` / `GroupCustomRoleGrant` — shaped exactly like
  `UserModuleRole`/`GroupModuleRole`, granting one `CustomRoleDefinition`
  to a user or an org group.
- Optional `ModuleRoleDefinition.permissions: tuple[str, ...] = ()` field
  (Phase 0 Q4) — additive, defaulted empty, so no existing module needs to
  change to keep working; Decision Management and Compliance can adopt it
  incrementally in a later, separate change, not as part of this phase.

**Why:** without a normalised, queryable permission-atom vocabulary
derived from the existing artefact-type registry, any "which permissions
does this role have" UI or check would either hand-maintain a duplicate
list (drifting from `get_all_registered_artefact_types()` the moment a new
module ships) or require a core-file edit per module — exactly the
per-module-hand-edit failure mode `CLAUDE.md`'s Modular Feature System
Boundary section exists to prevent, here applied to permissions instead of
artefact types or relationship link types.

## Phase 2 — Effective-permission resolution + `require_permission`

**Scope:**

- `get_effective_permissions(db, user_id, *, organization_id=None,
  project_id=None) -> set[str]` — a new, standalone function (per Design
  Principle 5, not threaded through `get_effective_project_roles`) that
  unions: (a) every permission implied by the caller's existing effective
  org/project roles and module roles, through a static, hand-authored
  mapping table (`ProjectRole.PROJECT_MANAGER -> {every artefact-type
  permission at every level}`, etc. — built once, per Design Principle 3,
  so an org that never touches custom roles sees no behavioural change at
  all); (b) direct `UserCustomRoleGrant`s; (c) `GroupCustomRoleGrant`s via
  the caller's transitive org-group membership (`effective_org_group_
  member_ids`, already exists, reused not reinvented).
- `require_permission(*allowed: str)` — a new FastAPI dependency factory,
  coexisting with (never replacing) `require_project_role`/`require_org_
  role`/`require_module_role`. An endpoint migrating to permission-based
  checks (Phase 4) swaps its dependency; every endpoint that doesn't
  migrate keeps working exactly as today, indefinitely.
- Server admin continues to bypass every check, consistent with every
  existing `require_*` dependency.

**Why:** this is the phase where the actual authorization decision gets
made — everything in Phase 1 is inert data until something resolves it
into "can this caller do this." Keeping it a parallel function (not a
rewrite of `get_effective_project_roles`) means Phase 2 ships with zero
risk of regressing the 8-source resolution algorithm's own, already
carefully-hardened behaviour (per `access-control-policy.md`'s documented
hardening history on that exact code path).

## Phase 3 — Backend API + frontend UI: custom-role management

**Scope:** CRUD endpoints for `CustomRoleDefinition` (org-admin-gated per
Phase 0 Q5), grant/revoke endpoints for both user and group targets, and
a `GET` endpoint listing `get_all_permissions()` grouped by artefact
type/module so the frontend never hardcodes the permission vocabulary
(mirroring `GET /orgs/{id}/module-roles`'s own existing shape). Frontend:
an org-settings "Custom Roles" page (naming per Phase 0 Q9) with a
permission-atom picker, extending `OrgAdminPage.tsx`'s existing role
multi-select to also show custom roles by their server-provided name —
the same generic-rendering pattern already used for module roles, not a
new UI paradigm. Playwright e2e + Storybook coverage per standing testing
requirements.

**Why:** Phases 1–2 are unusable without an actual way for an org admin to
create a role and grant it — this phase is what makes the mechanism
real rather than theoretical, and is deliberately scoped to management
only, not yet wired into any actual authorization check (that's Phase 4).

**MCP tools (2026-09-21 addendum) — read-only, and narrower than this
module's other read surfaces might suggest.** This session's general
instruction that every not-yet-built module plan get an explicit MCP-tools
commitment (**Decided by: User**) applies here, but Module 12's own
security framing above ("This is a security-sensitive plan... graded
against [tenant isolation / composition / no self-escalation]") means the
default "expose the safe list/get endpoints" template needs its own check
before being applied, not a mechanical copy of Compliance's or Decision
Management's precedent. **Decided by: Agent, after that check:**

- **Safe to expose read-only:** `list_permissions(organization_id)` (the
  `get_all_permissions()` structural vocabulary — artefact types × levels,
  plus the fixed administrative list) and `list_custom_roles
  (organization_id)` / `get_custom_role(organization_id, role_id)`
  **restricted to the role's own definition** (name, description,
  permission-atom set) — analogous to Compliance's `compliance_
  list_standards` or Decision Management's `list_decision_types`: this
  describes what a role *is*, not who holds it.
- **Not exposed — flagged rather than defaulted in.** Any endpoint listing
  *grants* (who currently holds a given custom role, whether via
  `UserCustomRoleGrant` or `GroupCustomRoleGrant`) is deliberately left off
  this list, and this plan does not recommend adding one by default. Unlike
  a standards catalogue or a decision-type list, a grant listing is an
  org's internal privilege map — which named individuals hold which
  elevated permissions. Handing that to an AI assistant caller is a real
  reconnaissance-value disclosure (exactly the information a compromised or
  over-trusted caller credential would most want) with no analogue in any
  MCP tool this codebase has shipped so far: every existing read-only tool
  exposes configuration or artefact data, never an access-control roster.
  If a genuine need for this later arises (e.g. an admin asking an AI
  assistant "who can approve Architecture decisions"), that should be a
  deliberate, explicitly user-approved addition made at that time — with
  the same identify → verify → remediate weight this plan's own Phase 6
  already commits to for the module as a whole — not something this
  addendum should pre-approve by extending the generic template
  mechanically.
- **Mutating endpoints** (`CustomRoleDefinition` create/update/delete,
  grant/revoke for either target) are excluded from the MCP surface
  entirely, per this codebase's unbroken read-only-only convention (`docs/
  mcp-server.md`). Worth stating explicitly here given how directly a
  grant/revoke action touches Design Principle 4 (no self-escalation): even
  a hypothetical future write-mode tool for this action would need its own
  dedicated review against that principle specifically, not just the
  ordinary `MCP_WRITES_ENABLED` gate every other mutating tool would need.
  `APPROVAL_ACTION_ROUTE_EXTRA` (`backend/app/modules/registry.py`) is not
  applied to these routes — it is specifically an approval-action marker,
  and a role grant is not an approval-shaped action — so the primary and
  sufficient defence here is the same one every other module in this
  codebase relies on first: simply declaring no `McpToolDefinition` for any
  of them.

## Phase 4 — First real consumer migration (proof against a live surface)

**Scope:** pick one or two existing, already-well-tested endpoints and
migrate their authorization dependency from a role-based check to
`require_permission`, using the Design Principle 3 mapping table so
existing behaviour for every org that hasn't touched custom roles is
provably unchanged (regression suite as the bar, same as Module 8 Phase 0
Q2's approach to migrating Requirements onto a generic engine). Recommend
starting with one Decision Management endpoint (`decision_owner`/
`decision_approver`, small and recently built, so its expected behaviour
is fresh and well-understood) rather than a high-traffic core endpoint
like requirement editing.

**Why:** migrating every existing authorization check across the whole
codebase in one pass is an enormous, regression-risky undertaking with no
proportionate benefit — this phase proves the mechanism against one real
surface first, deliberately small, before any wider adoption is
considered a separate, future decision (not scoped here).

## Phase 5 — Decision Management: per-decision-type approver binding

**Scope:** this is where the request that started this whole plan actually
gets fulfilled. Add an optional `approver_role` reference on
`DecisionTypeDefinition` (a plain string identifying either a fixed role
or, once this module exists, a `CustomRoleDefinition` id/key) — when set,
`decisions.service.approve_decision` requires the caller to hold that
specific role/permission for the Decision's own type, rather than the
current flat, single, project-wide `decision_approver` module role from
Module 4 Phase 0 addendum item 3. When unset (the default), behaviour is
unchanged — every project keeps the current flat-role behaviour unless an
admin explicitly opts a given Decision Type into a narrower approver.

**Why:** this is the concrete answer to the user's original ask ("certain
people only do some types of decisions"), and is deliberately built here —
in Decision Management, once this module exists — rather than waiting on
Module 8 (Governance), because Governance may land much later and the user
asked for this now. **This phase is explicitly superseded, not
duplicated, once Module 8 ships**: Governance's own Phase 2 ("Approval
policies... policies reference roles... per artefact type") is the
general version of exactly this mechanism, generalised across every
artefact type instead of hand-built once for Decisions. When Governance
exists, Decision Management's own `approver_role` field is a migration
candidate onto Governance's generic policy table — the same "generalise
now for what needs it today, migrate deliberately later, don't force
everything through Governance on day one" pattern Module 8's own Phase 0
Q2 already established for Requirements. Not blocking Phase 5 on
Governance's own, currently-unscheduled build is a direct trade-off the
user should confirm at this plan's own Phase 0 sign-off, not something
this plan assumes silently.

## Phase 6 — SOC 2 policy update + identify→verify→remediate review

**Scope:** `docs/soc2/policies/access-control-policy.md` gains a new
numbered item under Authorization describing this mechanism — mirroring
how module-contributed roles (item 4's own sub-paragraphs) and the
MCP-channel restriction are each documented — including: the permission-
atom vocabulary and its artefact-type-registry derivation; the grant
tables and their org-scoping; the composition rule (Design Principle 3)
with an explicit statement that it was checked against, and found
consistent with, item 2's tenant-isolation principle and the "a higher
tier already retains full access" composition rule every other scope in
that document already follows; and an update to the role-resolution
diagram's own "Scope, not exhaustiveness" note, adding this as a fourth
independently-resolving path alongside module-contributed roles and the
module-owned entity scope, per that note's own established pattern for
documenting a new resolution path without redrawing the whole diagram.
A full identify→verify→remediate review (per `change-management-and-
secure-development-policy.md`'s practice for security-sensitive changes)
is run before this module is considered complete, with its outcome
recorded in `docs/decisions.md`, the same weight Module 11's own plan
commits to and every module-role-system extension to date
(`docs/decisions.md`'s Phase 20/22/30 entries) has actually received.

## Phase 7 — Docs website coverage

**Goal:** add "Custom Roles" (naming per Phase 0 Q9) to `docs/website/` —
what a custom role is, the permission-atom model, how it composes with
existing fixed roles, and (once it exists) the per-decision-type approver
binding from Phase 5 — following the site's existing structure, tone, and
Mermaid-diagram conventions.

This phase is added per this session's instruction that every not-yet-built
module plan make explicit its docs-website coverage commitment (**Decided
by: User**, 2026-09-21); the specific scope and placement below are
**Decided by: Agent**.

**Checked explicitly, per this task's own instruction not to assume: this
module is not purely a backend/admin-config concern with no user-visible
surface.** Phase 3 ships a real org-settings UI page (the "Custom Roles"
picker extending `OrgAdminPage.tsx`) that an organisation admin — a user,
even if not an end-content-author — directly operates; this is the same
category of admin-facing surface the docs site already documents for
module-role assignment, org groups, and SSO mapping (per Phase 0 Q8's own
comparison to that precedent). It does not qualify for this repo's "no
user-visible surface" exception the way, say, Module 9's pure
relationship-wiring integration work does.

**Scope:**

- A docs-site page (grouped with the site's existing organisation-settings/
  administration documentation) covering: what a permission atom is
  (artefact type × View/Propose-Create/Manage/Approve-Baseline, per Phase 0
  Q1), how a custom role composes with existing fixed roles (Design
  Principle 3 — a broader existing tier always still satisfies a narrower
  check; a custom role only ever adds capability, it never removes or
  replaces the fixed roles) stated in plain, non-implementation language for
  an org-admin reader; how to create a role and grant it to a user or
  group; and the explicit invariant this plan itself is graded against — a
  custom role can never grant more than an `ORG_ADMIN` already has, and is
  never usable outside the organisation that defined it.
- A short Mermaid diagram of the composed resolution shape: server admin →
  org/project role → module-contributed role → custom-role grant, each an
  independently-resolving path per `access-control-policy.md`'s own
  role-resolution diagram note, adapted for a docs-site (non-implementation)
  audience.
- Once Phase 5 ships: a subsection on per-decision-type approver binding,
  cross-linked from Decision Management's own docs-website page (which by
  then documents the flat `decision_approver` role per its own Phase 6) —
  updating that page's approval-model description to note the optional
  narrower binding, rather than only adding a page here.
- A brief pointer to `docs/soc2/policies/access-control-policy.md` for
  readers who want the full authorization-policy account, mirroring the
  docs-site/policy split Module 11's own Phase 4 draws.
- **Screenshot requirement (2026-09-22 addendum).** Making this explicit
  here rather than leaving it implicit is **Decided by: User** (the same
  instruction as the phase itself, applied specifically to screenshots this
  time — `docs/plans/docs-website-plan.md`'s "Screenshots" section already
  bound this page to its standard, but this phase's Scope above never said
  so in as many words). This page is subject to that standard in full:
  1440×900 viewport, captured against the seeded demo dataset, stored
  under `docs/website/static/img/screenshots/`, real alt text plus a
  one-line caption. The clearest candidate screen (**Decided by: Agent**)
  is the "Custom Roles" picker's role-definition/permission-atom-
  composition screen (name, description, permission atoms) on
  `OrgAdminPage.tsx`. **Caution, mirroring this plan's own MCP-tools
  addendum above:** avoid a screenshot of a role's *grant list* (which
  named users or groups currently hold it) — this plan already treats that
  as a privilege-reconnaissance disclosure not safe to expose read-only via
  MCP, and the same reasoning applies to publishing it as a docs-site
  image. Capture the role-definition/creation view instead; if the
  grant/assign flow itself needs illustrating, use a screen state with no
  more than a single, clearly-fictional demo grant visible rather than a
  full roster.

**Status:** not started. Depends on Phase 3 (the custom-role management UI)
shipping — there is no real user-facing workflow to document before then.
The Phase 5 subsection depends additionally on Phase 5 shipping and can be
added incrementally once it does, without blocking the rest of this page.
Not a blocker for Phases 4–6.

## Documentation obligations specific to this module

Beyond the standard per-phase `docs/decisions.md` entry every module gets:
this module changes the authoritative answer to "what can this user do,"
so `docs/soc2/policies/access-control-policy.md` (Phase 6) is not optional
follow-up documentation — it is a completion criterion, the same as Module
11's own equivalent obligation. `docs/modules.md` also needs a note if the
optional `ModuleRoleDefinition.permissions` field (Phase 0 Q4 / Phase 1)
ships, documenting it as a new, additive, opt-in field alongside that
file's existing `ModuleRoleDefinition` documentation.

## Acceptance criteria (this plan's own synthesis — not from the overview, confirm with user)

- An organisation admin can define a custom role as a named set of
  permission atoms, without writing code or waiting on a new release.
- A custom role can be granted to a user or an organisation group.
- Every existing fixed role and module-contributed role continues to work
  exactly as today for an organisation that never creates a custom role —
  this module changes nothing by its mere existence.
- A broader existing tier (server admin, org admin, project manager)
  continues to satisfy any permission check without a separate grant.
- Only an organisation admin can create, edit, or grant a custom role.
- A custom role is never usable outside the organisation that defined it.
- At least one real, previously role-gated endpoint is demonstrably
  authorized via the new permission-based path, with the existing
  regression suite passing unchanged (Phase 4).
- A Decision Type can optionally require a specific role to approve
  Decisions of that type, defaulting to today's flat behaviour when unset
  (Phase 5).
- `docs/soc2/policies/access-control-policy.md` documents the mechanism,
  reviewed against its own tenant-isolation and composition invariants,
  before this module ships to production.
