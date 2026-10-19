# Project Instructions

## Validation

- User inputs may be written casually and can include imprecise terminology
- Agents must not only validate their own outputs but also challenge assumptions made by other agents where relevent.

## Documentation Requirements

- Prefer diagrams in documentation wherever they will improve clarity
- Be consise, and to the point.
- User Mermaid diagrams by default where possible
- Validate Mermaid diagrams before finalising to ensure they render correctly (no broken fences, no malformed syntax, no dangling nodes)
- Exception: screenshots/images in README.md do not need explanatory text immediately before or after them. The diagram rule above is about Mermaid diagrams conveying structure/flow that needs a reading key; README screenshots are illustrative product shots and a short caption (e.g. a table cell above each image) is sufficient — they must not be padded with "what this shows / why it matters" prose to satisfy the diagram rule.

When writing requirements:
- every requirement must include explicit reasoning
- Reasoning must state:
    - Why the requirement exists
    - What risk, defect class or constraint it addresses
    - The expected outcome if implemented

Any documentation output must maintain logical coherence, hierarchical consistancy and technology alignment.

All source files must include file-level documentation describing:
- The purpose of the module
- The responsibilities of the module
- Any important design decisions
- External dependencies or integrations

Example:

```python
"""
Module: user_service

Provides user account management functionality including:
- User creation
- User lookup
- User lifecycle management

This module is used by the API layer and should not directly access
HTTP request objects.
"""
```

When adding in documentation, be short and consise. Don't duplicate information that is only a few lines away in code.

Documentation should be about the latest state, not old states as this:
- dilutes the usefulness of the documentation
- causes more tokens to be used
- less readable to humans

## Function Documentation

Every function, method, and class must have documentation explaining:
- What it does
- Parameters and their types
- Return values
- Exceptions that may be raised
- Important side effects

Example:
```python
def calculate_total(items: list[Item]) -> Decimal:
    """
    Calculates the total cost of a collection of items.

    Args:
        items: List of items to calculate.

    Returns:
        The total monetary value of all items.

    Raises:
        ValueError: If an item has an invalid price.
    """
```

## Architecture and Environment Requirements

- The project must include a Docker Compose stack for testing, and this stack may also be used for general local running.
- The project must include documentation that:
  - describes what the project is
  - explains how to set up the development environment
  - explains how to run the project in both development and production environments
- The architecture should be designed with future scaling in mind, while starting with a single frontend container and a single backend container.
- The project should use PostgreSQL as its backend data store.
- The project must provide a method for monitoring service health, including container health checks and a Prometheus-compatible metrics endpoint that can be scraped for monitoring.
- The project should support Loki-based log aggregation and Tempo-based tracing, and the documentation should include setup instructions for both, including how to configure and use Grafana Alloy for shipping logs, traces, and metrics to these systems.
- As some requirements may be sensitive, designs must keep security at the forefront of architectural decisions.

## Compliance: SOC 2 Policy Adherence

- `docs/soc2/policies/` contains this project's adopted SOC 2 policy set (information security, access control, change management/secure development, system operations/monitoring/logging, incident response, vendor management, data classification/confidentiality, encryption/key management, data retention/disposal, risk assessment, security awareness training) and `docs/soc2/trust-services-criteria-mapping.md` maps them to the Security and Confidentiality Trust Services Criteria. These are binding on agent work in this repository, not just descriptive.
- Before making a change that touches authentication, authorization/RBAC, secrets or credentials, logging/audit trails, data retention or deletion, multi-tenant data isolation, or third-party/vendor integrations, consult the relevant policy in `docs/soc2/policies/` and follow it.
- Do not introduce a change that regresses a control described in these policies (e.g. weakening org/project-scoped authorization checks, logging or returning a Restricted-classified value such as a password hash or secret, storing a new secret in plaintext without noting it as a gap, bypassing the audit-logging pattern in `backend/app/services/audit.py` for a mutating action) without first flagging it explicitly to the user — do not silently ship a regression against an adopted policy.
- Follow [change-management-and-secure-development-policy.md](docs/soc2/policies/change-management-and-secure-development-policy.md)'s practice for security-sensitive changes specifically: run the existing test suites, and for anything touching the areas above, perform the same identify → verify → remediate review this codebase's own hardening passes use (see `docs/decisions.md`), recording the outcome there.
- These policies document existing gaps candidly (e.g. no CI gate, no account lockout, plaintext OIDC client secret) rather than hiding them — do not treat a documented gap as license to introduce further, unrelated ones. If new work closes one of these gaps, update the corresponding policy's "Known Gaps / Exceptions" section and the control matrix's Status column to reflect it.
- This section does not change the authority of [docs/requirements.md](docs/requirements.md), which remains the product requirements source of truth; the SOC 2 policies govern *how* changes are made, not *what* the product does.

## Frontend UX Style Guide Adherence

- [docs/ux-style-guide.md](docs/ux-style-guide.md) is binding on new and reworked frontend UI in this repository, not just descriptive — it is the direct output of a full UX audit ([docs/plans/completed/ux-audit-2026-08.md](docs/plans/completed/ux-audit-2026-08.md)) and states the rules the existing UI itself is being brought into line with.
- Before adding a new settings surface, create/edit flow, confirmation dialog, or destructive action in the frontend, consult the style guide's principles and patterns (settings hierarchy depth model, platform-default override visibility, create-as-a-layer, one-component-per-pattern, confirmation tiers, feedback-on-every-mutation, accessible control naming) and follow them rather than copying the nearest existing inconsistent example — "what did the last screen near this one do" is explicitly the failure mode the style guide exists to stop.
- Where a shared component the style guide calls for (`Tabs`, `SidePanel`, `Popover`, a two-tier confirm, `Toast`) does not exist yet, check [docs/plans/completed/ux-audit-2026-08.md](docs/plans/completed/ux-audit-2026-08.md)'s roadmap table first — it may already be scoped or in progress. Building a fifth one-off version of a pattern the style guide names is the exact debt this document was written to stop accruing (see that audit's "the newest feature already reproduces the pattern" finding).
- More generally, UI elements should use common/shared components, not per-page reimplementations — this applies even to element shapes the style guide hasn't explicitly named yet. Before building a new piece of frontend UI, check whether an equivalent already exists elsewhere in the codebase (another page's form field group, list/table shape, badge, toggle, etc.). If it does but isn't set up as a shared component yet, extract it into one *and update the existing call site(s) to use it too* — landing the new page on a shared component while leaving the original page on its own bespoke copy just adds a second inconsistent implementation instead of removing the first one, and is the same failure mode as skipping this check entirely.
- If a change must deviate from the style guide for a specific reason, say so explicitly to the user rather than silently diverging, and consider whether the style guide itself needs updating.
- Every create form for a linkable item type includes `QuickLinkField` (`frontend/src/components/QuickLinkField.tsx`) and creates its links with `useCommitQuickLinks` once the record exists; omitting it needs a stated reason, recorded in `docs/decisions.md`. See the style guide's "Pattern: quick-link on create" for the contract and the forms that deliberately omit it.
- Every create form for a taggable item type (every registered artefact type) includes `TagField` (`frontend/src/components/TagField.tsx`) and applies the chosen tags with `useCommitTags` once the record exists, beside `QuickLinkField`; a record's detail page passes `<RecordTags>` to `RecordHeader`'s `tags` prop, and a record list adds `TagFilterField` with `useTagFilter` and sends the `tag`/`tag_mode` parameters. A new item type needs no backend tag code (tags are keyed by the registered type string), but its list endpoint takes `TagFilter` (`services/tags.py`) as a dependency. Omitting any of these needs a stated reason in `docs/decisions.md`. See the style guide's "Pattern: tags".
- Every project-scoped record list takes `project_scope: ProjectScope = Depends()` (`services/project_scope.py`) and passes its single-project list logic to `ProjectScope.collect` with the same `(module, sub-component)` gate its own endpoint requires, never a hand-written cross-project query; its row schema derives from `ProjectScopedRow`; its page uses `useProjectScope` + `ProjectScopeFilter`, shows `ProjectScopeLabel`, links to `rowProjectId(row, projectId)` and keeps rows from another project read-only. A list that cannot be widened needs a stated reason in `docs/decisions.md` (a test lists the exemptions). Any code that reads a *related* project on the caller's behalf goes through `link_nesting.can_open_project`, which applies the token's project scope. See the style guide's "Pattern: list scope filter (nested projects)".
- A create form takes every field the record's edit form edits, through the same field-group component (`RequirementFields`, `PainPointScoreFields`, or the shared `*FormModal`), so a field added later reaches both; a field deliberately left out of one needs a stated reason in `docs/decisions.md`. See the style guide's "Pattern: create and edit share one field group".
- Any enum, status, or role value rendered to a user — a dropdown/filter `<select>` option, a table cell, a badge — must go through its existing label map (e.g. `REQUIREMENT_STATUS_LABEL`, `CHANGE_REQUEST_STATUS_LABEL`, `PROJECT_ROLE_LABEL` in `frontend/src/api/types.ts`), never the raw backend enum string (`in_review`, `project_administrator`). When adding a new enum value, add its label to the same map at the same time, not inline wherever it's first rendered. This has been missed repeatedly, including on pages where a sibling element used the correct label map two lines away for the same value — see the style guide's Principle 12.
- This does not change the authority of [docs/requirements.md](docs/requirements.md); the style guide governs UI *pattern/structure* choices, not product scope.

## Modular Feature System Boundary

- This project's modular feature system (`docs/plans/completed/compliance-module-plan.md` phases 0-4, `docs/modules.md`) exists specifically so core files never need per-module edits — see that plan's own "Design history" section for the repeated correction that got it there. A **core file** (anything outside `frontend/src/modules/<key>/` or `backend/app/modules/<key>/` — e.g. `frontend/src/App.tsx`, `frontend/src/components/Layout.tsx`, `frontend/src/pages/OrgAdminPage.tsx`/`ProjectAdminPage.tsx`, `backend/app/main.py`) must never `import` a symbol from a specific module's own directory. The only files allowed to import from `modules/<key>/` are that module's own files, plus the generic module-loading infrastructure (`frontend/src/modules/registry.ts`, `backend/app/modules/registry.py`).
- If a core file needs to render or call something a module contributes — a nav-rail entry, a settings panel, a router, an RBAC role, an MCP tool, a bundle-export hook, a shared context/provider — extend the module's declarative registration schema instead of importing directly: `TierAModuleDefinition` (`frontend/src/modules/types.ts`) on the frontend, `ModuleDefinition` (`backend/app/modules/registry.py`) on the backend. Follow the render-prop/callback convention those types already use (`orgAdminSections[].render`, `routes`, `get_router()`, `get_project_router()`, `get_global_router()`, `resolve_file_owner_project_id`) rather than inventing a one-off import as a shortcut.
- If the existing schema has no field for what you need (a new nav-rail item, a new kind of workspace section, a new provider), add a new generic field to `TierAModuleDefinition`/`ModuleDefinition` and have the core file consume it generically for every module — do not special-case the one module you're currently working on inside the core file.
- This has already happened once (docs/plans/completed/compliance-module-plan.md Phase 18: `Layout.tsx` imported a compliance-specific context directly and hardcoded a compliance-only URL pattern/nav label instead of going through the registration mechanism) — treat this as a known, specific failure mode to check for on every module-touching change, not just a one-time reminder.
- The boundary is not only about `import` statements — it also covers core *data* a module's own rows need registered. A core column/table bound to a fixed, non-extensible type (e.g. a Python `enum.Enum`, or any closed vocabulary) that a module would need a new value added to is the same failure mode as a direct import, even though adding an enum member isn't literally an `import`: it's still a per-module hand-edit to a core file. The only correct fix is to make the core column/type itself generically module-registrable — a plain validated value checked against a registry-merged set (`backend/app/models/relationship.py`'s `ArtefactLink.source_type`/`target_type`, validated against `backend/app/modules/registry.py`'s `get_all_registered_artefact_types()`, is the reference implementation) — never a static per-module addition to the core enum/column, and never a new bespoke mechanism reinvented per module either. Rule of thumb the user has stated directly: **a core change to support a module must be a generic extension point — "functionality to allow modules to perform their behaviour" — never the module's own behaviour or data hand-edited into the core file.**
- This has also already happened once at the data layer, not just the import layer: Module 0 (Platform Foundations) Phase 2's `ProjectSequenceCounter.artefact_type` was bound to the fixed `ArtefactType` enum instead of getting the same dynamic treatment `ArtefactLink.source_type`/`target_type` got one phase earlier in the very same module — found and corrected when Module 4 (Decision Management) Phase 1 hit it, 2026-09-21 (see `docs/decisions.md`'s "Module 4 (Decision Management) Phase 1" entry). Treat "does this core table/enum need a per-module value added?" as its own explicit check on every module-touching change, alongside the import check above — it's easy to satisfy the import rule while still violating its underlying principle this way.
- The same failure mode also shows up as a **plain frontend constant or stylesheet**, not just a backend enum/column — a closed `Record<Kind, ...>` map in a core `.ts` file (or a CSS custom property in a core stylesheet) that a module needs its own entry added to is exactly the same violation, just outside the database. `frontend/src/api/types.ts`'s `ENTITY_ACCENT_COLOR`/`EntityAccentKind` map (the left-border accent colour a list row renders with per entity kind) briefly grew a `"compliance"` entry, and a matching `--color-entity-compliance` variable was added to the core `frontend/src/styles/theme.css`, before being caught and corrected during Module 4 (Decision Management) Phase 5, 2026-09-21 (a second attempted entry, `"decision"`, made the pattern visible) — see `frontend/src/modules/entityAccentColor.ts`'s own docstring for the corrected mechanism: a module registers its own colour as a literal `{ light, dark }` hex pair on its own `TierAModuleDefinition.entityAccentColor` (`frontend/src/modules/types.ts`), resolved client-side via `useEntityAccentColor()`, never as a new case in a core map or a new variable in a core stylesheet. When adding any module-facing "kind"-keyed display concern — an accent colour, an icon, a badge tone, a CSS class — check whether it's a closed core `Record`/enum/stylesheet a module would need its own entry in, and if so build (or reuse) a registry-backed extension point instead, the same way `artefact_types`/`org_creation_choices`/`entityAccentColor` already do.

## MCP Agent Skill

- A new or changed MCP tool updates the agent skill in the same change. Core tools (`mcp-server/server.py`): update `mcp-server/skill/reqtrack-mcp/SKILL.md` and run `python scripts/generate_skill_reference.py` in `mcp-server/`. Module tools (a `mcp_tools` entry or a `ReportDefinition`, which becomes a tool without touching `mcp-server/`): update the module's `mcp_guidance.md` if the workflow changes and run `python scripts/generate_mcp_module_tools_reference.py` in `backend/`.
- `mcp-server/tests/test_skill.py` and `backend/tests/test_mcp_skill_reference.py` fail when this is skipped. Fix the skill, never the test. A module that declares MCP tools must set `ModuleDefinition.mcp_guidance` (see `docs/mcp-server.md`'s "Agent skill").

## Human-Readable Codes on Every Item Type

- Every item type a user can create, link to or refer to (every registered artefact type: core and module) must have a project-scoped, human-readable code in the `PREFIX-nnn` shape (`REQ-001`, `DEC-003`, `RSK-002`, `FND-001`, `ENG-001`), so it can be named in conversation, found from the other side of a link, and cited in a report. A new item type ships with its code in the same change.
- Generate it with the shared `services.sequences.generate_unique_code(db, project, artefact_type, prefix)` (per-project counter, never reused, race-safe), stored as a `unique_code` column that is unique per project. Do not invent a per-module counter. Put the code in the type's artefact summary label (`"FND-001 title"`) so the link finder, trace and reports show it, and give a migration for an existing type a backfill that numbers existing rows in the order they were created and moves the counter past them.
- Show the code where a record is identified (list, detail header) and as a small, muted suffix, never a prominent label, in shared link lists (see the Links panel in [docs/ux-style-guide.md](docs/ux-style-guide.md)). A project import numbers its records afresh.
- Show a code through `<RecordCode>` or `useRecordCode()` (`frontend/src/components/RecordCode.tsx`, `hooks/useRecordCode.ts`), never as the raw `unique_code`: they apply the one rule for adding the project code (`ACME-REQ-001`), and a hand-formatted code ignores the organisation's switch and the person's preference. Server-side, a qualified code is `services.codes.qualify`; look one up with `find_record_by_qualified_code`.
- A type that can be owned by the organisation (not a project) numbers from the organisation's counter: pass the `Organization` to `generate_unique_code`, and show the code qualified by the organisation code through `<ScopedRecordCode>`/`useRecordOwnerCode`. A type with no code yet (the only exemptions are the compliance requirement and its 1:1 children) is a gap recorded in `docs/decisions.md`; do not add a new type without one.

## Time and Dates

- Store and transmit every point in time that has already happened (a created, edited or logged time, an audit event) in UTC: timezone-aware `datetime`s, ISO 8601 with a `Z` or offset on the wire. The backend never stores or formats a server-local time and never converts a past instant to a person's timezone; browsers do every conversion to and from local time (display, date and time pickers, "today").
- A date and time in the future that a person schedules (a review at 09:00, a meeting, a reminder, a deadline) is stored as the local wall-clock time plus the IANA timezone name it was meant in (`Australia/Sydney`, never a bare offset such as `+10:00` and never only the local time), so it still means 09:00 there after a daylight-saving change. The browser supplies the zone from the person's picker or setting. Resolving it to a UTC instant is done only where something must act at that moment (a scheduler, a due check, an export), with `zoneinfo`, at that moment, and the result is not stored back over the wall-clock value. Once it has happened, the recorded time (when it was done) is UTC as above.
- A calendar date a person chooses with no time of day (a due date, an engagement date) is stored as a plain `date` and means that person's own day. A rule that asks whether such a date has passed uses the caller's day: the browser sends it as `X-Client-Date` (`frontend/src/utils/localDate.ts`, read on the backend through `services.client_date.effective_today()`), never the server's UTC date on its own.
- Reason: a time fixed in the future as a UTC instant drifts by an hour against the wall clock when daylight saving changes; the UTC day lags the local day for part of every day east of Greenwich (before 10:00 in Sydney), so mixing a locally entered date with the server's UTC "today" made a contact logged that morning read as future-dated ("Never engaged"); and a server that converts times to a timezone has to guess the right one. Keeping storage in UTC and conversion in the browser removes both defects.
- When adding a field, comparison, report or export that involves time, say in the change which of the three shapes it is (a past instant in UTC, a future scheduled wall-clock time with its IANA zone, or a person's calendar date) and test the boundary hours (for example 09:00 at UTC+10 and 23:00 at UTC-8) and, for a scheduled time, a daylight-saving change (the same wall-clock time a week either side of it). Existing code that compares dates against the UTC day (risk and compliance review dates, the overdue reports) is to move to `effective_today()` when touched; do not add new ones.

## Nested (Hierarchical) Projects

- This project supports parent/child project nesting (`Project.parent_project_id`, `docs/decisions.md`'s "Hierarchical (parent/child) projects" entry). Whenever a change adds a new **project-scoped config/definition table** — a closed, per-project vocabulary a project can define its own rows of (the shape `ActionTypeDefinition`/`DecisionTypeDefinition`/`CustomFieldDefinition` already share) — explicitly decide, at design time, whether a child project with none of its own rows should fall back to its nearest ancestor's, the same way `resolve_effective_action_types` (`backend/app/services/project_hierarchy.py`) already does for Action Types. Record the decision (`Decided by: User`/`Decided by: Agent`) in `docs/decisions.md` and the relevant plan doc **before or during implementation**, not as a follow-up once someone notices the table doesn't nest.
- This has already been missed twice: Decision Types (Module 4 Phase 4, shipped with no fallback, corrected 2026-09-22 after explicit user review — see that entry in `docs/decisions.md`) and `ProjectSequenceCounter.artefact_type` (Module 0 Phase 2, corrected when Module 4 Phase 1 hit it, 2026-09-21). Treat "does this new project-scoped table need the same fallback Action Types already have?" as its own explicit checklist item on every change that adds one — alongside the Modular Feature System Boundary checks above, not instead of them.
- The reference implementation is `resolve_effective_action_types`: own rows if any exist, else the nearest ancestor's (walking `Project.parent_project_id`, cycle-safe, capped), else empty at an unconfigured root — always on, independent of `role_inheritance_mode`/RBAC. A definition table's own delete/rename endpoints stay scoped to rows it actually owns; only the *list*/*effective-set-membership* read paths resolve the fallback. A root-only seeding hook is the other half of making the fallback real in practice — if new rows are seeded automatically on project creation, seed only a root project (`parent_project_id is None`), the same way `routers.projects.create_project`'s own `seed_action_types` call is gated; seeding every project unconditionally (including children) means the fallback path never actually triggers. If a new table's shape doesn't fit this exactly (e.g. it's org-scoped, or has no natural "empty means inherit" reading), say why in the decision log rather than silently skipping the check.

## Organisation Defaults a Project Can Hide

- Any project-scoped list that inherits organisation-level rows (a `*TypeDefinition` with an organisation tier and a project view of it) must let the project **hide** a default and **restore** it. Delete on an organisation-backed row hides it in that project; a delete that only shows an explanatory message is a defect.
- Mechanism: a tombstone in `ProjectDefinitionSuppression` (`services/definition_suppression.py`: register a `definition_kind`, subtract `get_suppressed_ids` in the effective-list resolver, call `forget_definition` when the organisation row is deleted). For a typed vocabulary use `TypeVocabulary` (`services/type_vocabulary.py`) and the shared endpoint bodies in `services/type_vocabulary_routes.py`; on the frontend `ProjectTypeVocabularyPanel` already provides the hide confirm and `RestoreOrgDefaultsButton`. Hidden defaults must also travel in the project bundle (export/import).
- Reason: otherwise a project is stuck with every default or invents its own workaround per table. See [docs/ux-style-guide.md](docs/ux-style-guide.md)'s "Pattern: organisation defaults in a project" and `docs/decisions.md`'s Phase 15 entry.

## Users and Groups on Parity

- Users and groups are treated on parity across the product: anything that can be applied to a user (an owner, assignee, decision maker, reviewer, role or permission grant, notification recipient, filter, report column) should also be applicable to a group, and anything that can be applied to a group should be applicable to a user. "Group" means both organisation groups and project groups unless a design says otherwise.
- Reason: a team is often the accountable party, and a user-only field forces a nominee who then leaves, leaving the record unowned; one-off group support added field by field produces several inconsistent mechanisms.
- When adding or changing a field, picker, gate, filter, notification or report that refers to a person, check whether a group can be used there too. If it cannot, either build the group case in the same change or raise it explicitly with the user and record the gap and the reason in `docs/decisions.md`; do not silently ship a user-only version.
- Prefer one shared mechanism (a principal reference type and a shared picker) over per-module group columns, and follow the Modular Feature System Boundary rules when a module needs it: a generic extension point, never a per-module hand-edit of a core file.
- Group membership gates (such as "the owner may propose") use effective membership: org groups transitively, project groups with their nested org groups, exactly as `services/rbac.py` already resolves them. A group never confers more than its members would hold individually, and a group from another organisation is always rejected.

## Documentation and Decision Governance

- The requirements document at [docs/requirements.md](docs/requirements.md) is fully authoritative and must not be changed by the agent. All decisions should be made in compliance with the requirements laid out in this document.
- The architecture document at [docs/solution-architecture.md](docs/solution-architecture.md) should be updated when there are architectural changes.
- The decisions log at [docs/decisions.md](docs/decisions.md) should be used to record architectural and implementation decisions.
- Every new decision recorded from now on — in `docs/decisions.md`, in `docs/plans/completed/compliance-module-plan.md`'s "Open decisions" list and individual phase specs, or in any comparable plan/decisions doc added later — must say who made it: **Decided by: User** (an explicit instruction, or the user's answer to a clarifying question) or **Decided by: Agent** (the implementing session's own judgment call, absent explicit direction). This exists because a "settled" decision an agent made on its own is not the same weight as one the user actually gave, and a later session needs to know which is which before treating either as fixed — an agent decision can be revisited on its own judgment where a user decision needs the user's sign-off to change. This applies going forward only; do not spend effort retroactively re-tagging existing entries.

## Plan Lifecycle

- `docs/plans/` holds live plans; closed ones live in `docs/plans/completed/` so a reader can tell what is still in progress. See [docs/plans/README.md](docs/plans/README.md).
- When the last phase of a plan is done and its Status table reads N/N, `git mv` it to `docs/plans/completed/`, rewrite every reference to the old path (including code comments), run `python scripts/check_doc_links.py` until it passes, and update the memory index. A plan that is only paused or has an open phase stays put.
- **Source files never reference plans.** Code, comments, docstrings, tests, migrations, stories and config must not name a plan document, a plan's phase, question number or "the plan" — plans are working papers that get archived and rewritten. Write the rationale itself in the comment (the why, in the present tense); for a decision with a longer account, cite `docs/decisions.md` or a durable doc (`docs/modules.md`, `docs/solution-architecture.md`, a policy). Plan references belong only in `docs/`. `scripts/check_doc_links.py` fails on a source file naming a plan document or citing a "Phase N".
- Reason: a stale plan that reads as current misleads the next session, and an unchecked move leaves hundreds of dangling references. The checker also runs in CI's `docs` job, from `.githooks/pre-commit` and as `backend/tests/test_doc_links.py`.

## Docs Website Maintenance

- After developing a new feature or making a change to existing behaviour, review the documentation site under `docs/website/` to determine whether it needs updating as a result. This is a distinct check from the README/decisions-log/architecture-doc requirements elsewhere in this file — the docs website is a separate, published artifact (see `docs/plans/completed/docs-website-plan.md`) and does not get updated automatically just because those other docs were.
- Make the judgement call on necessity explicitly: does the change add/remove/rename a user-facing feature, workflow, screen, API, config option, or concept the site documents or should document? If yes, update the relevant page(s) as part of the same change, following the site's existing structure, tone, and Mermaid-diagram conventions (see the Documentation Requirements section above). If no, no action is needed — do not pad the site with updates for purely internal/backend-only changes that have no user-visible surface.
- Treat this the same as the other "fix/update now, don't defer" rules in this file: if an update is deemed necessary, perform it in the same change rather than noting it for later.

## README Requirements

The README.md must always reflect the current state of the project.

When making significant changes, update the README to include:
- Project purpose
- Installation instructions
- Configuration requirements
- Usage examples
- Architecture overview
- Development workflow (a short section is sufficient — a pointer/summary linking to `docs/development.md` for the full local-setup/testing/linting/CI instructions satisfies this; the detailed how-to-hack-on-this-repo content belongs there, not duplicated inline)
- Known limitations
- Code Quality Rules
- Prefer clear, maintainable code over clever solutions.
- Do not introduce undocumented behaviour.
- Do not remove existing documentation unless it is incorrect.
- Update documentation when changing functionality.
- Add tests for new functionality.
- Code warnings (compiler/type-checker, linter, build-tool, and library deprecation warnings) must be fixed, not ignored, suppressed, or left in place. Do not silence a warning with an inline disable/ignore comment as a substitute for fixing it, unless the warning is a documented false positive.
- Do not edit linting configs (e.g. eslint/ruff/flake8/tsconfig rule sets and similar) to disable, downgrade, or narrow a rule as a way to make a warning go away. Fix the underlying code instead. A rule change is only acceptable when the rule itself is wrong for the project, and that must be raised with the user explicitly rather than done silently.
- When a dependency's current version is flagged as deprecated (by the library itself, its registry, or a warning it emits), upgrade it to a supported version or replacement. Never downgrade or pin to an older version to make a deprecation warning go away.
- When you find an issue or bug — including one unrelated to the current task, discovered incidentally during a review, hardening pass, or test run — fix it as part of the same piece of work. Never classify it as "out of scope to fix"; document-and-defer is not an acceptable substitute for fixing it.

## Testing Requirements

- Every new UI feature must come with a Playwright end-to-end test covering it — no UI feature is considered done until it has e2e coverage.
- Every new piece of frontend UI (component or page) must also have Storybook coverage set up as part of the same change — no new frontend development is considered done without accompanying Storybook stories, in addition to the Playwright e2e requirement above.
- Every backend change must come with a test that verifies the behaviour matches the request and pins it against future deviation/regression.
- `backend/scripts/seed_demo_data.py` (a small, realistic manual-demo dataset) and `backend/scripts/seed_e2e_dataset.py` (the fixed persona/org/project dataset the Playwright suite is written against) must be kept in sync with the current schema and feature set. Whenever a change adds/renames/removes a model field, table, enum value, or a whole feature area, check whether either script needs a corresponding update — new fields should be populated with a sensible demo value rather than left at a default that hides the feature, and a removed/renamed field or relationship must not be left referencing something that no longer exists. Treat a script that fails to run, or that no longer demonstrates a feature it used to, as a bug the same as a failing test.
- Tests (Playwright specs and backend pytest alike) must not depend on state left behind by another test, or by an earlier run of themselves, having already run — each test must pass whether it runs alone, first, last, or repeated back-to-back against the same database, not only as part of one specific full-suite ordering starting from a freshly seeded database. A spec that deletes/renames a named seed fixture (e.g. an action type called "Review") and then asserts that exact seeded name exists on a later run is non-idempotent — prefer creating and cleaning up the spec's own dynamically-named fixtures over mutating shared named seed data, or otherwise make the spec tolerant of already-mutated state. If you find a non-idempotent test while working on anything in this repo, fix it so it can be run standalone or out of order, per the general fix-don't-defer rule above — do not just note it and move on.
- Never run more than one `pytest` invocation against this repo's backend at the same time (including one left running in the background while you start another in the foreground, or two agents/sessions each running their own). All backend tests share one on-host/container test database, and two concurrent runs reliably wedge each other — spurious `ERROR`s and failures across unrelated test files, not a real regression — costing a full re-run to even tell the difference. Run pytest invocations strictly one at a time, and wait for one to fully finish (check backgrounded output, don't just fire another) before starting the next.

## IPv6 Support

- Every network listener this project ships (nginx, uvicorn, the MCP server, the docs server, any new service) must accept IPv6 as well as IPv4. IPv6 is never excluded intentionally: not to dodge a probe, a DNS quirk, a CI runner or an "IPv4 is enough" assumption.
- Reason: IPv6-only and IPv6-first hosts exist, and an IPv4-only listener fails there in ways that look like app faults (a container reported unhealthy while it works, a client that resolves `localhost` to `::1` and is refused).
- How: nginx gets both `listen PORT;` and `listen [::]:PORT;`; Python servers bind `::` (dual-stack on Linux) rather than `0.0.0.0`. Container health probes address `127.0.0.1` (`scripts/check_health_probes.py` enforces it) because that works on every host; that is a probe choice, not a licence to drop the IPv6 listener.
- If IPv6 genuinely breaks something, fix the cause or raise it with the user; do not remove IPv6 support to make it go away.

## Frontend Dependency Changes

- CI (`ci.yml`) and `frontend/Dockerfile` both install with Node 24; `frontend/.nvmrc` pins the same major version for local use (`nvm use` in `frontend/`). Keep all three in lockstep when bumping Node in future — a mismatched local Node major version bundles a different npm major version, which can resolve transitive optional dependencies differently and write a `package-lock.json` that passes locally but fails CI's `npm ci` with "Missing: `<pkg>` from lock file". This has happened repeatedly.
- After adding, removing, or bumping a package in `frontend/package.json`, run `frontend/scripts/sync-lockfile.sh` (extra arguments pass through to `npm install`, e.g. a package name to add) rather than a bare `npm install` — it refuses to run under the wrong Node major version and re-verifies with `npm ci` before you commit.
- A tracked pre-commit hook (`.githooks/pre-commit`, wired up automatically via `frontend`'s `postinstall` script) also runs `npm ci --dry-run` whenever `frontend/package.json` or `package-lock.json` is staged, and blocks the commit if they're out of sync — this doesn't replace the step above, it's the backstop for when it's skipped.

## Playwright MCP Usage

- Use the Playwright MCP browser tools (`mcp__playwright__*`) sparingly — driving a live browser through MCP consumes tokens much faster than reading code or running the Playwright test suite directly.
- Prefer running the existing Playwright spec suite (via the CLI/Docker Compose stack) for verification. Reserve the MCP browser tools for targeted, one-off investigation of something the spec suite and static code reading can't resolve (e.g. confirming an actual rendered UI state or chasing a hard-to-reproduce bug).

## Agent Tool Isolation

- Do not default to `isolation: "worktree"` when spawning implementation agents in this repo. Edit the working tree directly.
- Only use `isolation: "worktree"` when there's a concrete reason: multiple agents genuinely running in parallel over the same files, or the user explicitly wants an easy-rollback branch for a risky change.
- Sequential background agents (one implementation pass after another, even across separate `Agent` calls) do not need isolation — nothing else is touching the repo concurrently, so a worktree adds `git merge`/`git worktree remove` bookkeeping and more complex resume prompts (exact worktree paths) for no benefit.

## Git Commits

- Never run `git commit` in this repo as the agent, even when a fix is small, already verified, or clearly needed to unblock CI/a PR. Staging and diffing (`git add` to inspect, `git diff`, `git status`) is fine; creating the commit itself is not.
- Finish the work, verify it, and hand it back described and ready to commit — the user commits it themselves. If the work is urgent (e.g. a failing PR check), say so and let them decide the timing, rather than committing to save a round trip.
- This applies regardless of how confident the fix is or how many times committing has been fine before in this session — each commit is the user's call, every time, not something a prior "yes" in the conversation extends to.

## Critical Thinking & Challenge

Do not blindly agree with the user. Treat their assumptions, proposals, and conclusions as hypotheses to evaluate. Actively look for flaws, risks, trade-offs, failure modes, missing information, and better alternatives.

If you disagree, say so clearly and near the top of the response. Give uncomfortable truths when they are relevant. Explain your reasoning and distinguish facts, assumptions, uncertainty, and judgement.

When the user pushes back, reconsider your reasoning but do not capitulate without genuinely new information or a valid flaw in your position. If you change your mind, explain why.

Think beyond the immediate request. Consider the underlying problem, future requirements, adjacent use cases, maintainability, and opportunities for simple, reusable designs. For example, when adding configuration, consider whether a general key/value or structured configuration is more appropriate than a single-purpose setting.

Think outside the box and suggest materially better approaches when you see them, but do not over-engineer for hypothetical needs. Keep future-proofing proportional to likely value.

Optimise for truth, correctness, robustness, and good decisions—not agreement or simply satisfying the literal request.