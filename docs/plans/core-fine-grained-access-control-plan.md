# Fine-Grained Access Control (Custom Roles & Permissions) — Core Platform Capability — Implementation Plan

See [future-modules-2026-09-index.md](future-modules-2026-09-index.md) for
cross-cutting architecture referenced throughout, including the existing
role-resolution model this plan extends rather than replaces.

**Reclassified from optional module to core platform capability, 2026-09-23.**
**Decided by: User.** This was originally scoped and numbered as "Module 12,"
an optional, per-project/org toggleable module living outside the ten-module
roadmap sequence (same shape as Module 11). It is reclassified here as core
platform capability instead — always present, not gated behind a
`docs/modules.md` toggle or the module registry — for two concrete reasons
surfaced when the user questioned the "optional module" framing directly:

1. `docs/requirements.md`'s C-U-01/C-U-03 describe the existing fixed roles
   as a **minimum** ("Organisations must have **at minimum** the permission
   roles of...") rather than a ceiling, and `backend/app/models/enums.py`'s
   own module docstring already flags customisable permissions as an
   anticipated baseline direction — *"Ossa (v1) intentionally uses a small,
   fixed set of organisation and project roles rather than a customisable
   permission system (customisable roles/attributes are a Pelion (v2)
   concern per docs/requirements.md)"* — i.e. the authoritative requirements
   document itself already treats this as core v2 product direction, not an
   optional bolt-on comparable to Compliance or Decision Management.
2. Concrete architectural coupling already exists: Decision Management
   (Module 4) Phase 8 is blocked on this capability existing, and Governance
   (Module 8)'s own approval-policy engine is designed to reference roles
   this capability supplies. Gating that behind a per-project toggle would
   mean some projects structurally cannot use mechanisms other, non-optional
   parts of the roadmap are built to expect.

Module 11 (Acting on Behalf Of) was considered for the same reclassification
and explicitly **not** moved — it has no equivalent grounding in
`docs/requirements.md`, and nothing else in the roadmap is blocked on it (see
that plan's own Status). It remains an optional module.

**Practical consequence of "core, not a module":** this capability's
implementation lives directly in core files (`backend/app/services/rbac.py`,
core org/project routers, `frontend/src/pages/OrgAdminPage.tsx`), the same
way Module 0's relationship model does — not under `backend/app/modules/
<key>/` or `frontend/src/modules/<key>/`, and with no `ModuleDefinition`/
`TierAModuleDefinition` registration or `docs/modules.md` toggle entry for
itself. It is unconditionally available to every organisation, the same way
the existing fixed `OrgRole`/`ProjectRole` enums are today.

**Original source (unchanged by the reclassification):** not from
`future-modules-2026-09-overview.md` — requested directly by the user
2026-09-21, arising out of a Decision Management (Module 4) discussion
about restricting who can approve which Decision Type. The user explicitly
asked for this to be tracked as its own standalone plan rather than folded
into Decision Management or Module 8 (Governance) — the right call; see
"Why this is not another module's problem" below (title kept as-is: the
reasoning there is about ownership, not about module-vs-core status).

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

**Status:** Proposed. Phase 0 complete (2026-09-23) — see "Status / Resume
Here" below. Picked up immediately after Module 4 (Decision Management),
ahead of Module 1, for the same reason Module 4 jumped the queue: it
unblocks a concretely blocked phase (Module 4's own Phase 8) and every
subsequent content module's approval design can build against it from day
one instead of deferring its own approver-binding question the way Module
4 already had to. As core infrastructure (like Module 0), it is not an
enablement toggle any module or project can be without — every
organisation gets it, whether or not any given org chooses to actually
define a custom role.

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
- **Not Module 0's problem**, for the same reason Module 11 wasn't, and this
  reasoning is unaffected by this plan's own reclassification to core: both
  this plan and Module 0 are now core infrastructure, but Module 0 is
  deliberately scoped to policy-neutral data plumbing with no authorization
  implications of its own. Bundling an authorization redesign into it would
  force security review onto every module riding on Module 0, or let this
  slip through under Module 0's lighter framing. "Core" describes where the
  code lives and whether it's toggleable, not a reason to merge two plans
  with very different review weight.

## Design principles carried over from the existing model (non-negotiable, not open questions)

These are not Phase 0 discussion points — they are established, tested
invariants this plan must not weaken, restated here because they will be
consulted at every phase below:

1. **Additive, never a replacement.** `OrgRole`/`ProjectRole` and every
   existing module-contributed role stay exactly as they are, for every
   organisation that never touches custom roles. An organisation that opts
   into custom roles gets *additional* ways to grant capability; it can
   never lose the fixed roles as a fallback, and this capability ships no
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
   of `rbac.py` and is exercised by dozens of call sites; this plan adds
   a **parallel** `get_effective_permissions` function (Phase 2) rather
   than threading a new concept through the existing one, the same way
   module-contributed roles resolve independently of the core
   org/project-group hierarchy today (documented explicitly in
   `access-control-policy.md`'s role-resolution diagram note).

## Status / Resume Here

3 / 7 phases complete. Phase 3 is next.

| # | Phase | Status |
|---|-------|--------|
| 0 | Exploratory: permission-atom shape & open questions | [x] Complete (2026-09-23) — all nine questions resolved with the user, several beyond this plan's original recommendation (generic sub-type scoping; `grant_roles` generalized to the whole role system) — see "Open questions for Phase 0" above |
| 1 | Data model: permission atoms, sub-type registry, `CustomRoleDefinition`, grants | [x] Complete (2026-09-23) — see `docs/decisions.md`'s "Fine-Grained Access Control (core) — Phase 1 complete" entry for the full account, including the `CustomRoleDefinition.scope` restriction and the Decision Management sub-type provider's flat-org-union design decision, both Decided by: Agent |
| 2 | Effective-permission resolution + `require_permission` | [x] Complete (2026-09-23) — see `docs/decisions.md`'s "Fine-Grained Access Control (core) — Phase 2 complete" entry for the full account, including the static fixed-role mapping, the org-scoped-custom-role-applies-org-wide design decision, and the path-params-only (never query-bindable) security choice behind `require_permission`'s scope resolution, all Decided by: Agent |
| 3 | Backend API + frontend UI: Role Management | [ ] Not started |
| 4 | First real consumer migrations (proof against live surfaces) | [ ] Not started |
| 5 | Decision Management: per-decision-type approval scoping | [ ] Not started |
| 6 | SOC 2 policy update + identify→verify→remediate review | [ ] Not started |
| 7 | Docs website coverage | [ ] Not started — depends on Phase 3 |

## Phase 0 — Exploratory: Requirements Clarification & Design Validation

**Why this phase carries unusual weight:** like Module 11 (which remains an
optional module even after this plan's own reclassification to core, see
above), this plan has a
real security posture attached to its central design choice, not just an
implementation-cost trade-off — getting the permission-atom granularity or
the composition rule wrong is the kind of mistake that needs catching
before it ships, not after an audit.

### Open questions for Phase 0 — resolved 2026-09-23, all **Decided by: User**

Walked through individually with the user rather than accepted as a batch;
several went beyond this plan's original recommendation and required real
design work in the moment, not a mechanical pick between the two options
originally posed. Recorded here as final.

1. **Permission atom shape: `(artefact_type, level)` pairs, confirmed.**
   The four-tier taxonomy (View / Propose-Create / Manage / Approve-Baseline)
   crossed with every registered artefact type, plus a short hand-maintained
   administrative list. **Explicit reasoning for why this satisfies "read and
   write must be separate" without going fully granular:** `View` is its own
   independent atom, held or not held separately from every write tier — a
   role can be `{(X, View)}` alone, a pure read-only grant. Fully granular
   per-action atoms (the rejected option) would add finer slicing *within*
   write, a different axis, at the cost of a large hand-authored enumeration
   with no registry to derive it from — left as a genuine future refinement
   if a concrete case ever needs it, not built speculatively now.
2. **Scope model: reuse `ModuleRoleDefinition.scope` as-is, confirmed.** No
   second, parallel scope concept.
3. **Sub-type scoping: build it now, generically — not deferred to Phase 5.**
   This reverses the plan's original recommendation. Decision Types
   (`DecisionTypeDefinition`) are per-organisation *data*, not a fixed
   code-level enum like artefact types, so this can't just extend
   `get_all_registered_artefact_types()` — it needs a second, parallel,
   module-registrable callback: `get_subtypes(db, organization_id,
   artefact_type) -> list[str]`, merged across every module that registers
   one (mirroring the existing artefact-type-registry pattern, applied to
   *dynamic, per-org* vocabularies instead of a static code-level set). The
   permission atom becomes `(artefact_type, level, subtype: str | None)` —
   `None` means "every sub-type" (today's behaviour, unaffected for any
   artefact type with no registered sub-type provider), a specific value is
   validated against that org's *current* rows from the owning module's
   callback at grant time. **Consequence for Phase 5, below: this replaces
   the originally-planned `DecisionTypeDefinition.approver_role` field
   entirely** — Decision Management registers a `get_subtypes` callback
   returning its own Decision Type keys, and the approval check becomes a
   direct `require_permission` call scoped to that decision's type, with a
   `subtype=None` grant acting as a wildcard that satisfies any
   specific-subtype check (a broader grant implying a narrower one, the same
   composition principle already governing every other tier in this model).
   No new Decision Management field, no bespoke mechanism — the very case
   that motivated this whole plan is now just its first real consumer.
4. **Compose with module-contributed roles: yes, confirmed.** Optional
   `ModuleRoleDefinition.permissions` field, additive, defaulted empty.
5. **Who can create/edit/delete a `CustomRoleDefinition`: `ORG_ADMIN` only,
   confirmed, and explicitly not delegable via any permission atom** — no
   "manage custom roles" atom exists. This closes off the "mint a new,
   arbitrarily powerful role" escalation path entirely, independent of
   question 6 below.
6. **Role *assignment* (not creation): generalized to a single delegable
   `grant_roles` atom, going well beyond this plan's original custom-roles-
   only scope.** A holder of `grant_roles` may assign — unrestricted, with
   no "must already hold this permission" check — any of: fixed `OrgRole`/
   `ProjectRole` values, module-contributed roles, and custom roles, to any
   user or group. **Two roles stay carved out regardless:** `ORG_ADMIN`
   (only an existing `ORG_ADMIN` or server admin may grant it — the user's
   explicit instruction) and `MODULE_ADMINISTRATOR` (an *existing* invariant
   already in this codebase, unrelated to this plan — "can only be granted
   by a full server admin, never by another `MODULE_ADMINISTRATOR`" —
   `grant_roles` composes on top of that restriction rather than relaxing
   it). **Residual risk, to be documented explicitly and candidly in Phase
   6's SOC 2 write-up, not silently accepted:** because assignment is
   unrestricted, a `grant_roles` holder could assign an existing broad role
   (custom or otherwise) to themselves or an accomplice. The blast radius is
   bounded by whatever `ORG_ADMIN` chose to define or already grants —
   no *new* permission combination can be minted this way — but it is a
   real, deliberate scope of this permission, confirmed directly with the
   user, not an oversight. **Practical consequence for Phase 3/4/6, flagged
   explicitly:** `grant_roles` is a delegated path into the *existing*,
   already-shipped org/project/module role-assignment endpoints (today
   gated to `ORG_ADMIN`/`PROJECT_MANAGER`/etc.), which need an additional
   `require_permission("grant_roles")` authorization path alongside their
   current checks — a materially larger blast radius than "one small,
   already-well-tested endpoint," and its own explicit line item in Phase
   6's identify→verify→remediate review, not folded in quietly alongside
   the rest of that review.
7. **Grant surface: both direct user grants and group grants from the
   start, confirmed.** `UserCustomRoleGrant` / `GroupCustomRoleGrant`,
   shaped like `UserModuleRole`/`GroupModuleRole`.
8. **Frontend home: a single new org-settings page**, not scoped narrowly to
   "Custom Roles" — it needs to cover custom-role definition (`ORG_ADMIN`-
   only) and the new, broader `grant_roles`-based assignment surface (fixed
   roles, module roles, and custom roles together), since the user pointed
   out these aren't "always custom per se." Confirm the exact placement
   against the UX style guide's settings-hierarchy-depth model before Phase
   3 starts (unchanged from the original question — only the page's scope
   grew, not this obligation).
9. **Naming: "Role Management,"** not "Custom Roles" — chosen by the user
   specifically because the page now spans classic, module, and custom
   roles together, not custom roles alone.

**Exit criteria met.** Phase 1 can start.

## Phase 1 — Data model: permission atoms, sub-type registry, `CustomRoleDefinition`, grants

**Scope** (per Phase 0's resolved answers above):

- No new enum of permission atoms as a giant hand-maintained list — a
  `Permission` is derived data: `(artefact_type, level, subtype)` for every
  registered artefact type × the four levels × (every registered sub-type
  for that artefact type, if any, plus the `subtype=None` wildcard), plus a
  short, explicit list of non-artefact administrative permissions declared
  directly here (`manage_members`, `manage_settings`, `manage_integrations`,
  `grant_roles` — no "manage custom roles" atom; see Phase 0 Q5). A registry
  function, `get_all_permissions()`, mirrors `get_all_registered_artefact_
  types()`'s own shape.
- A second, parallel registry for **sub-type providers** (Phase 0 Q3):
  `get_subtype_providers() -> dict[str, Callable[[Session, UUID], list[str]]]`,
  merged from every module that registers one, keyed by artefact type. An
  artefact type with no registered provider only ever has `subtype=None`
  permissions — no behavioural change for any module that doesn't opt in.
  Decision Management registers its own provider for `"decision"`, returning
  that organisation's current `DecisionTypeDefinition` keys — this is the
  one piece of this phase that has a real consumer on day one (see Phase 5).
- `CustomRoleDefinition` — org-scoped (`organization_id` FK), `name`,
  `description`, `scope` (per Phase 0 Q2), and a `CustomRolePermission`
  join table (`custom_role_id`, `permission` string, encoding
  `artefact_type:level:subtype`) rather than an array column, so individual
  permission grants stay independently queryable and diffable — the same
  normalised-join-table precedent this codebase already uses everywhere
  else (never a serialized array/JSON blob for a set that needs per-row
  operations). A `subtype` value is validated against the owning module's
  registered provider (for that org) at write time, mirroring how
  `ArtefactLink.source_type` is validated against the merged artefact-type
  registry today.
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

**Status: Complete (2026-09-23).** Built as scoped above, with two points
resolved during implementation that weren't fully settled by Phase 0's own
text — both **Decided by: Agent**, full reasoning in `docs/decisions.md`'s
"Fine-Grained Access Control (core) — Phase 1 complete" entry, not
duplicated here:

1. `CustomRoleDefinition.scope` accepts only `"org"`/`"project"`, not an
   arbitrary module-owned entity scope the way `ModuleRoleDefinition.scope`
   can — a custom role has no declaring module to supply the
   `resolve_entity_organization_id` hook a third scope value would need.
2. Decision Management's `subtype_providers["decision"]` registration
   (`list_decision_type_names_for_organization`) returns a **flat union of
   Decision Type names across every project in the organisation**, not
   `resolve_effective_decision_types`'s per-project parent/child fallback —
   `DecisionTypeDefinition` is project-scoped data while a permission atom's
   `subtype` is compared directly against one specific decision's own type
   name at check time (Phase 5), never re-resolved through this provider
   after role-definition time, so there is no project hierarchy for this
   function itself to walk.

Exit criteria met — `docs/decisions.md`'s own entry has the full test/
verification account. Phase 2 can start.

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
- **Sub-type wildcard matching (Phase 0 Q3):** when checking whether a
  caller holds `(artefact_type, level, subtype="Architecture")`, a grant of
  `(artefact_type, level, subtype=None)` also satisfies it — a broader,
  unscoped grant implies every narrower, specific-subtype one, the same
  composition principle already governing every other tier in this model
  (Design Principle 3). The reverse never holds: a subtype-specific grant
  never satisfies a check for a *different* subtype or for the unscoped
  permission.
- Server admin continues to bypass every check, consistent with every
  existing `require_*` dependency.

**Why:** this is the phase where the actual authorization decision gets
made — everything in Phase 1 is inert data until something resolves it
into "can this caller do this." Keeping it a parallel function (not a
rewrite of `get_effective_project_roles`) means Phase 2 ships with zero
risk of regressing the 8-source resolution algorithm's own, already
carefully-hardened behaviour (per `access-control-policy.md`'s documented
hardening history on that exact code path).

**Status: Complete (2026-09-23).** Built as scoped above. Three points
resolved during implementation that Phase 0/this section's own text left
open, all **Decided by: Agent**, full reasoning in `docs/decisions.md`'s
"Fine-Grained Access Control (core) — Phase 2 complete" entry, not
duplicated here:

1. The static `ProjectRole`/`OrgRole` → permission mapping table, beyond
   the one worked example (`PROJECT_MANAGER`) this section's own text
   gave — `PROJECT_ADMINISTRATOR`/`STAKEHOLDER`/`MEMBER`/`ORG_ADMIN` each
   needed their own mapping, derived from C-U-01/C-U-03's clarifications.
2. An org-scoped `CustomRoleDefinition`'s grant applies throughout every
   project in its organisation (not only at org-level checks) — the
   alternative would make `scope="org"` pointless for any permission atom
   other than the four administrative ones.
3. `require_permission` reads its `organization_id`/`project_id` scope
   off `request.path_params` directly rather than as a normal FastAPI
   dependency argument with a query-parameter fallback — a deliberate
   security choice (an `Optional[UUID] = None` argument would let a
   caller redirect which org/project gets checked via the query string on
   a route missing the matching path segment), not a style preference.

Exit criteria met — `docs/decisions.md`'s own entry has the full test/
verification account. Phase 3 can start.

## Phase 3 — Backend API + frontend UI: Role Management

**Scope:** CRUD endpoints for `CustomRoleDefinition` (`ORG_ADMIN`-gated per
Phase 0 Q5, not delegable), grant/revoke endpoints for both user and group
targets, and a `GET` endpoint listing `get_all_permissions()` grouped by
artefact type/module so the frontend never hardcodes the permission
vocabulary (mirroring `GET /orgs/{id}/module-roles`'s own existing shape).
**Assignment endpoints (grant/revoke, for fixed org/project roles, module
roles, and custom roles alike) additionally accept `require_permission
("grant_roles")` as an alternative to their existing `ORG_ADMIN`/
`PROJECT_MANAGER`/etc. checks** (Phase 0 Q6) — except granting `ORG_ADMIN`
itself (stays `ORG_ADMIN`/server-admin-only) and `MODULE_ADMINISTRATOR`
(stays server-admin-only, per that pre-existing invariant). This is a wider
change than a purely additive new surface: it adds a second, delegated
authorization path onto *existing*, already-shipped membership-management
endpoints, not just new custom-role endpoints — treat it with the same
care as any change to those endpoints' existing tests and behaviour for
callers who don't hold `grant_roles`, which must be provably unaffected.

Frontend: a single new org-settings **"Role Management"** page (naming and
scope per Phase 0 Q8/Q9 — deliberately not "Custom Roles," since the page
also surfaces fixed and module-role assignment via `grant_roles`), with a
permission-atom picker (including the sub-type dimension, grouped by
artefact type) for defining custom roles, and a unified assignment view
covering fixed, module, and custom roles by their server-provided name —
the same generic-rendering pattern already used for module roles, not a
new UI paradigm. **Access to this page itself needs explicit design**: an
`ORG_ADMIN` reaches it via the existing org-admin surface, but a non-admin
`grant_roles` holder needs their own path to the assignment half of this
page without necessarily seeing the `ORG_ADMIN`-only role-definition half —
confirm this split against the UX style guide's settings-hierarchy-depth
model before implementation, not assumed here. Playwright e2e + Storybook
coverage per standing testing requirements.

**Why:** Phases 1–2 are unusable without an actual way for an org admin to
create a role and grant it — this phase is what makes the mechanism real
rather than theoretical. Unlike the original, narrower plan, this phase
now also wires `grant_roles` into the *existing* role-assignment surface,
since the user extended that atom's scope beyond custom roles alone (Phase
0 Q6) — Phase 4 below still owns proving this against the regression
suite, but the endpoint changes themselves land here since they're the
same CRUD/assignment surface as everything else in this phase.

**MCP tools (2026-09-21 addendum) — read-only, and narrower than this
capability's other read surfaces might suggest.** This session's general
instruction that every not-yet-built module (or, as here, core-capability)
plan get an explicit MCP-tools commitment (**Decided by: User**) applies
here, but this plan's own security framing above ("This is a
security-sensitive plan... graded
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
  This exclusion is, if anything, reinforced by Phase 0 Q6's later
  generalization of `grant_roles` beyond custom roles to the *entire*
  existing role system — a hypothetical future write-mode tool touching
  role assignment would need review against a much larger blast radius
  than originally scoped here, not a smaller one.
  `APPROVAL_ACTION_ROUTE_EXTRA` (`backend/app/modules/registry.py`) is not
  applied to these routes — it is specifically an approval-action marker,
  and a role grant is not an approval-shaped action — so the primary and
  sufficient defence here is the same one every other module in this
  codebase relies on first: simply declaring no `McpToolDefinition` for any
  of them.

## Phase 4 — First real consumer migrations (proof against live surfaces)

**Scope:** two migrations, not one, following from Phase 0's resolved
answers:

1. **The `grant_roles` integration itself (Phase 0 Q6).** The existing
   org/project/module role-assignment endpoints gain `require_permission
   ("grant_roles")` as an alternative to their current checks (built in
   Phase 3); this phase is where that's proven against the full regression
   suite, confirming a caller without `grant_roles` sees no behavioural
   change and a caller with it can assign any role except `ORG_ADMIN`/
   `MODULE_ADMINISTRATOR`. This is the larger, higher-blast-radius
   migration flagged in Phase 0 Q6 and Phase 3 above — it touches
   already-shipped, heavily-tested membership-management code directly, so
   the regression suite passing unchanged is the bar, not a sampling of it.
2. **One smaller, additional endpoint**, kept from the original plan as a
   second, independent proof point on a narrower surface: a Decision
   Management endpoint (`decision_owner`/`decision_approver`, small and
   recently built, so its expected behaviour is fresh and well-understood)
   migrated to `require_permission` using the Design Principle 3 mapping
   table.

**Why:** migrating every existing authorization check across the whole
codebase in one pass is an enormous, regression-risky undertaking with no
proportionate benefit — this phase proves the mechanism against two real
surfaces, deliberately bounded, before any wider adoption is considered a
separate, future decision (not scoped here). The `grant_roles` migration
can't be deferred to "a separate future decision" the way further adoption
can, since Phase 3 already built its endpoint-side integration — this
phase is what proves that integration is actually safe.

## Phase 5 — Decision Management: per-decision-type approver binding

**Scope:** this is where the request that started this whole plan actually
gets fulfilled — and, per Phase 0 Q3's resolution, more simply than
originally planned. **No new field on `DecisionTypeDefinition`.** Decision
Management registers a `get_subtypes` provider (Phase 1) returning that
organisation's current Decision Type keys for artefact type `"decision"`.
`decisions.service.approve_decision` calls `require_permission` for
`(decision, approve_baseline, subtype=<this decision's own type>)` instead
of (or as well as, during a transition — see below) the current flat,
single, project-wide `decision_approver` module role from Module 4 Phase 0
addendum item 3. A caller holding the flat `decision_approver` role gets an
implied `(decision, approve_baseline, subtype=None)` grant via the Design
Principle 3 mapping table (Phase 2), which the sub-type wildcard rule
(Phase 2) satisfies for every specific Decision Type — so **every project
keeps today's flat-approval behaviour with zero configuration**, and an
org only narrows approval to specific types by granting a role (fixed or
custom) scoped to `(decision, approve_baseline, subtype="Architecture")`
for whichever types it wants restricted, entirely through Phase 3's Role
Management UI — no Decision-Management-specific admin surface needed at
all.

**Why:** this is the concrete answer to the user's original ask ("certain
people only do some types of decisions"), and is deliberately built here —
in Decision Management, once this capability exists — rather than waiting
on Module 8 (Governance), because Governance may land much later and the
user asked for this now. **This phase is explicitly superseded, not
duplicated, once Module 8 ships**: Governance's own Phase 2 ("Approval
policies... policies reference roles... per artefact type") is the general
version of exactly this mechanism, generalised across every artefact type.
Because this phase no longer adds its own field to `DecisionTypeDefinition`
(the generic sub-type-scoped permission check *is* the mechanism), there is
nothing Decision-Management-specific left to migrate away from when
Governance ships — Governance's own policies become just another way to
grant the same underlying `(decision, approve_baseline, subtype=...)`
permission, not a replacement for a bespoke field. Not blocking Phase 5 on
Governance's own, currently-unscheduled build remains a direct trade-off,
now lower-cost than originally assessed given there's no field to later
deprecate.

## Phase 6 — SOC 2 policy update + identify→verify→remediate review

**Scope:** `docs/soc2/policies/access-control-policy.md` gains a new
numbered item under Authorization describing this mechanism — mirroring
how module-contributed roles (item 4's own sub-paragraphs) and the
MCP-channel restriction are each documented — including: the permission-
atom vocabulary (including the sub-type dimension) and its artefact-type-
registry derivation; the grant tables and their org-scoping; the
composition rule (Design Principle 3) with an explicit statement that it
was checked against, and found consistent with, item 2's tenant-isolation
principle and the "a higher tier already retains full access" composition
rule every other scope in that document already follows; and an update to
the role-resolution diagram's own "Scope, not exhaustiveness" note, adding
this as a fourth independently-resolving path alongside module-contributed
roles and the module-owned entity scope, per that note's own established
pattern for documenting a new resolution path without redrawing the whole
diagram.

**Its own explicit sub-item, not folded in quietly (Phase 0 Q6):** the
`grant_roles` atom and its residual risk — a holder can assign any
existing role (fixed, module, or custom) to anyone, unrestricted, except
`ORG_ADMIN` and `MODULE_ADMINISTRATOR`, which stay admin-only. Document
this as a deliberate, confirmed design property (candidly, the same way
this repo already documents other known gaps), not an oversight — an org
that grants `grant_roles` to a non-`ORG_ADMIN` user should understand that
user can hand out any other existing role, including ones broader than
their own.

A full identify→verify→remediate review (per `change-management-and-
secure-development-policy.md`'s practice for security-sensitive changes)
is run before this capability is considered complete, with its outcome
recorded in `docs/decisions.md`, the same weight Module 11's own plan
commits to and every module-role-system extension to date
(`docs/decisions.md`'s Phase 20/22/30 entries) has actually received. The
`grant_roles` integration into existing role-assignment endpoints (Phase
3/4) is this review's own explicit line item, given its wider blast radius
than the rest of this capability — not assessed only as part of the
capability's overall review.

## Phase 7 — Docs website coverage

**Goal:** add "Role Management" (naming per Phase 0 Q9) to `docs/website/`
— what a custom role is, the permission-atom model (including the
sub-type dimension), how it composes with existing fixed roles, the
`grant_roles` delegated-assignment capability and its documented scope,
and (once it exists) the per-decision-type approval scoping from Phase 5
— following the site's existing structure, tone, and Mermaid-diagram
conventions.

This phase is added per this session's instruction that every not-yet-built
module plan make explicit its docs-website coverage commitment (**Decided
by: User**, 2026-09-21); the specific scope and placement below are
**Decided by: Agent**.

**Checked explicitly, per this task's own instruction not to assume: this
capability is not purely a backend/admin-config concern with no
user-visible surface.** Phase 3 ships a real org-settings UI page (the
"Role Management" page extending `OrgAdminPage.tsx`) that an organisation
admin — a user, even if not an end-content-author — directly operates;
this is the same category of admin-facing surface the docs site already
documents for module-role assignment, org groups, and SSO mapping (per
Phase 0 Q8's own comparison to that precedent). It does not qualify for
this repo's "no user-visible surface" exception the way, say, Module 9's
pure relationship-wiring integration work does.

**Scope:**

- A docs-site page (grouped with the site's existing organisation-settings/
  administration documentation) covering: what a permission atom is
  (artefact type × View/Propose-Create/Manage/Approve-Baseline × optional
  sub-type, per Phase 0 Q1/Q3), how a custom role composes with existing
  fixed roles (Design Principle 3 — a broader existing tier always still
  satisfies a narrower check; a custom role only ever adds capability, it
  never removes or replaces the fixed roles) stated in plain,
  non-implementation language for an org-admin reader; how to create a
  role and grant it to a user or group; what `grant_roles` lets a delegate
  do and its documented scope (per Phase 6); and the explicit invariant
  this plan itself is graded against — a custom role can never grant more
  than an `ORG_ADMIN` already has, and is never usable outside the
  organisation that defined it.
- A short Mermaid diagram of the composed resolution shape: server admin →
  org/project role → module-contributed role → custom-role grant, each an
  independently-resolving path per `access-control-policy.md`'s own
  role-resolution diagram note, adapted for a docs-site (non-implementation)
  audience.
- Once Phase 5 ships: a subsection on per-decision-type approval scoping,
  cross-linked from Decision Management's own docs-website page (which by
  then documents the flat `decision_approver` role per its own Phase 6) —
  updating that page's approval-model description to note the optional
  narrower, sub-type-scoped permission, rather than only adding a page
  here.
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
  is the "Role Management" page's role-definition/permission-atom-
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

**Status:** not started. Depends on Phase 3 (the Role Management UI)
shipping — there is no real user-facing workflow to document before then.
The Phase 5 subsection depends additionally on Phase 5 shipping and can be
added incrementally once it does, without blocking the rest of this page.
Not a blocker for Phases 4–6.

## Documentation obligations specific to this capability

Beyond the standard per-phase `docs/decisions.md` entry every module or
core-capability plan gets: this capability changes the authoritative answer
to "what can this user do," so `docs/soc2/policies/access-control-policy.md`
(Phase 6) is not optional follow-up documentation — it is a completion
criterion, the same as Module 11's own equivalent obligation. `docs/
modules.md` also needs a note if the optional `ModuleRoleDefinition.
permissions` field (Phase 0 Q4 / Phase 1) ships, documenting it as a new,
additive, opt-in field alongside that file's existing `ModuleRoleDefinition`
documentation — that field is the one part of this plan any actual module
touches; this plan itself is not a `docs/modules.md` entry.

## Acceptance criteria (this plan's own synthesis — not from the overview, confirm with user)

- An organisation admin can define a custom role as a named set of
  permission atoms, without writing code or waiting on a new release.
- A custom role can be granted to a user or an organisation group.
- Every existing fixed role and module-contributed role continues to work
  exactly as today for an organisation that never creates a custom role —
  this capability changes nothing by its mere existence.
- A broader existing tier (server admin, org admin, project manager)
  continues to satisfy any permission check without a separate grant.
- Only an organisation admin can create, edit, or delete a custom role
  definition — never delegable.
- A holder of the `grant_roles` permission can assign any fixed, module, or
  custom role to a user or group — except `ORG_ADMIN` and
  `MODULE_ADMINISTRATOR`, which stay admin-only — with this scope
  documented candidly, not discovered later.
- A custom role is never usable outside the organisation that defined it.
- At least two real, previously role-gated surfaces are demonstrably
  authorized via the new permission-based path — the existing
  role-assignment endpoints via `grant_roles`, and one additional
  standalone endpoint — with the existing regression suite passing
  unchanged (Phase 4).
- Decisions can optionally require a specific role (fixed or custom) to
  approve a given Decision Type, via a sub-type-scoped permission, defaulting
  to today's flat behaviour when no narrower grant exists (Phase 5).
- `docs/soc2/policies/access-control-policy.md` documents the mechanism,
  including the `grant_roles` residual-risk scope, reviewed against its own
  tenant-isolation and composition invariants, before this capability ships
  to production.
