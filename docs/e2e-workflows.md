# Multi-org, multi-persona end-to-end workflow suite

This document catalogues the jobs-to-be-done this suite verifies, the exact personas and credentials it uses, and how to re-run the whole thing from scratch. The suite exists to answer one question with evidence, not assertion: **do ReqTrackManager's permission boundaries and requirement-lifecycle guarantees actually hold, in the real browser UI, under realistic multi-tenant data?**

It complements the existing `tests/playwright/tests/{golden-path,pelion-v2,mockup-engagement}.spec.ts` specs, which exercise the feature set as the single bootstrap admin in one organisation. This suite instead spans three organisations, seven projects, and seven distinct personas whose access differs in specific, deliberate ways, plus a dedicated pass at trying to break the rules a well-behaved user would never test.

A later, broader pass (see the "Full-product coverage pass" section below) added specs for every remaining page and workflow not already covered by the above — review scheduling, change-request tasks/voting, stage review deadlines and completion, the structural/groups/fields/templates halves of Project and Org Admin, org-wide 2FA, the server-admin user directory and bans, notifications/favourites, project history, comment editing/attachments, the CSV import wizard, requirement list filters, and preferences/theme/landing-page — following the same "prove it against the real UI, and prove the server enforces it independent of the UI" discipline established here.

## How to run it, end to end, from a clean slate

```bash
cd tests/container
docker compose down -v && docker compose up --build -d   # fresh database, incl. the Keycloak instance sso.spec.ts needs
docker compose exec backend python -m pytest -q          # backend unit/integration suite

# re-bootstrap the server admin (pytest truncates all tables, including it)
docker compose restart backend

docker compose exec backend python scripts/seed_e2e_dataset.py   # already baked into the image, no copy step needed
docker compose exec backend python scripts/seed_demo_data.py     # tests/badge-filters.spec.ts logs in as this dataset's demo.admin@example.com

cd ../playwright
npx playwright test        # runs every spec, including tests/e2e-workflows/
```

The seed script is idempotent — re-running it against a database that already has `E2E Alpha Robotics` prints a message and exits without changes. Its primary supported usage is against a freshly migrated database, per the sequence above.

## Personas

All seeded by `backend/scripts/seed_e2e_dataset.py` through the real API (not direct DB writes — see that file's module docstring for the one documented exception). Password for every persona: `E2ePass123!`.

| Persona | Email | Org roles | Project roles | Why this persona exists |
|---|---|---|---|---|
| Server Admin (zero orgs) | `e2e-serveradmin@example.com` | *none* | *none* | Proves server-admin is a narrow, cross-tenant management role — not a backdoor into any org's or project's actual content. |
| Org Admin, two orgs | `e2e-orgadmin-ab@example.com` | `org_admin` in Alpha + Beta | auto-PM on all 4 Alpha/Beta projects (project creators are auto-added as PM) | Proves one account can administer multiple, unrelated organisations. Also plays the "has approval permission" side of the change-request separation-of-duties workflow. |
| Org Admin, separate org | `e2e-orgadmin-g@example.com` | `org_admin` in Gamma only | auto-PM on both Gamma projects | A non-overlapping admin — the multi-tenancy baseline every other persona is compared against. |
| Stakeholder, single project | `e2e-stakeholder-a@example.com` | `member` in Alpha | `stakeholder` on Alpha-1 only | A user scoped to exactly one project in one org — and the "lacks approval permission" side of the change-request workflow. |
| Stakeholder, single project (second) | `e2e-stakeholder-a2@example.com` | `member` in Alpha | `stakeholder` on Alpha-1 only | A second stakeholder alongside the one above, so change-request voting has a real two-voter tally rather than a single vote. |
| Member, two orgs | `e2e-member-ab@example.com` | `member` in Alpha + Beta | `member` on Alpha-1 and Beta-1 | A user whose access spans two different organisations' projects, with no admin/creator rights anywhere. |
| Orphan candidate | `e2e-orphan@example.com` | *none* (left Alpha via the same self-service endpoint the zero-org server admin uses) | *none* | A second, independent zero-org-membership account (distinct from the server admin persona) for the user-directory/deactivate/ban workflow, so exercising deactivation and bans doesn't touch an account other specs also log in as. |
| Project manager, no org role | `e2e-projectmgr-g@example.com` | `member` in Gamma only | direct `project_manager` on Gamma-1; direct `stakeholder` on Gamma-3 (shows up as forward-inherited on Gamma-4) | Exercises hierarchical projects' relaxed parent-manage-only creation path and the `parent_required` bypass-closure block (docs/decisions.md's "Hierarchical projects" entry) — deliberately has zero org-level standing, unlike every other project-manager persona above. |

Orgs: **E2E Alpha Robotics**, **E2E Beta Software**, **E2E Gamma Labs**, two projects each (Alpha-1/2, Beta-1/2, Gamma-1/2), 6-8 requirements per project across 2 components × 2 categories, plus a couple of pre-existing change requests for volume. Alpha-1's first requirement (`HW-FN-001`) is locked (status `approved`) by the seed script specifically to give the change-request and bypass-attempt workflows something to target immediately. A 7th project, **Delta-1 Terminology Demo** (in Alpha, 3 requirements, no cross-references to the other 6), is seeded with a fixed C-C-03 terminology override (`stage`→"Phase", `requirement`→"Spec", `change_request`→"ECR") dedicated solely to `terminology-override.spec.ts` — no other spec may depend on it being at, or away from, that override. Gamma gets two more: **Gamma-3 Hierarchy Parent** / **Gamma-4 Hierarchy Child**, a fixed pair demonstrating both hierarchical-projects RBAC-cascade directions at once (Gamma-4 mirror-all-inherits from Gamma-3; Gamma-3 also consumes members from Gamma-4) — dedicated solely to `project-hierarchy.spec.ts`.

## Workflows

### 1. Server admin sees the deployment, not the tenants
**Persona:** Server Admin (zero orgs). **Spec:** `server-admin-scope.spec.ts`

- **Job to be done:** as the person responsible for the deployment as a whole, I can see every organisation that exists (for oversight/support), without that visibility becoming a way to read or act on any specific org's or project's actual content.
- **Steps:** log in → Server Management → Organisations lists all orgs on the system → Global → Projects is empty → opening any org's admin page reveals nothing (org details load, since that's a documented bypass, but users/groups/resources all 403, so the page never renders past its loading state).
- **Expected outcome:** full deployment visibility at the directory level, zero content access, confirmed both in the UI and via a raw API call.

### 2. One admin, two organisations
**Persona:** Org Admin, two orgs. **Spec:** `multi-org-admin.spec.ts`

- **Job to be done:** as the admin of two separate client organisations, I manage both from one account without them bleeding into each other.
- **Steps:** log in → see both orgs' existing projects → create a new project in Alpha through the real form → create a new project in Beta → both appear in the projects list → Gamma (a third org this user has no relationship to) is invisible, both as a project list entry and as an org-admin page.

### 3. A genuinely separate org admin
**Persona:** Org Admin, separate org. **Spec:** `single-org-admin.spec.ts`

- **Job to be done:** as an org admin with no relationship to any other org on the deployment, my administration is fully self-contained.
- **Steps:** log in → manage Gamma (create a project, no org picker shown since there's only one org to choose from) → Alpha and Beta are entirely invisible.

### 4. Project access is per-project, not per-org
**Persona:** Stakeholder (single project) and Member (two orgs). **Spec:** `project-access-scope.spec.ts`

- **Job to be done:** being a member of an organisation doesn't imply access to every project in it — access is granted project by project, and it can span multiple orgs for the same person.
- **Steps:** stakeholder sees exactly Alpha-1 (not Alpha-2, despite being an Alpha org member); cross-org member sees exactly Alpha-1 and Beta-1 (not Alpha-2/Beta-2/Gamma); the cross-org member's attempt to create a new project is rejected server-side (`Only org admins or project creators may create projects.`) since plain `member` grants neither right.

### 5. Change-request approval is a separate action from submission
**Persona:** Stakeholder submits, Org Admin (PM) approves. **Spec:** `change-request-approval-separation.spec.ts` — the centerpiece workflow.

- **Job to be done:** a stakeholder who spots a problem with an approved (locked) requirement can propose a fix, but cannot approve their own proposal.
- **Steps:** stakeholder opens the locked requirement's project, raises a change request against it, submits it — and now sees no Approve/Reject controls at all (see "Product gaps found" below for why that assertion is meaningful); a raw API call attempting to self-approve still 403s; a different user (the project's PM) logs in separately, finds the same change request, and approves it through the real UI; the requirement reflects the approved change.

### 6. Attempts to bypass the requirement lifecycle
**Personas:** rotates through Org Admin (PM), Stakeholder, Member. **Spec:** `workflow-bypass-attempts.spec.ts`

Each of these is a deliberate attempt to route around a guarantee, followed by confirmation it was actually blocked:

- **Edit a locked requirement directly.** PM approves Alpha-1's stage (bulk-locks every requirement still in draft/reviewed). A locked requirement's detail page offers no edit form at all — and a raw API `PUT` against the same requirement still 409s, so the guarantee doesn't depend on the UI simply not offering the button.
- **Archive-and-recreate to dodge history.** The stakeholder (not a PM/administrator) sees no Archive control on a locked requirement at all. The PM archives it, then creates a brand-new requirement with the *exact same name*. The new requirement gets a distinct `unique_code` — identifiers are never reused, even for archived requirements — so there is no way to "become" the old one; its version history stays exactly as it was.
- **Decide a change request without the role, via a direct API call.** A project member with no PM role attempts the decide endpoint directly against an existing change request (not just avoiding the button) — 403.
- **Cross-org ID guessing.** A single-org user (the stakeholder) is handed another org's project id and attempts to open it both via a raw API call and by navigating the browser directly to that URL — 403, and the UI renders nothing for it either way.

### 7. SSO login against a real identity provider
**Personas:** two Keycloak-native users, not from `seed_e2e_dataset.py` — `sso-admin@example.com` (in the `reqtrack-org-admins` group) and `sso-member@example.com` (in `reqtrack-members`), both seeded directly into the `tests/container/keycloak` realm import (`tests/container/keycloak/realm-export.json`), password `KeycloakPass123!`. **Spec:** `sso.spec.ts` (added Massif v3, E-U-01).

- **Job to be done:** a user authenticating through an organisation's own identity provider, not a password this app ever sees, ends up with exactly the account and role their IdP group says they should have — and an organisation can gate access to a specific group entirely, separate from which role a group maps to.
- **Steps:** the browser drives the real flow — an org's branded `/login/{slug}` page → click "Sign in with SSO" → redirected to Keycloak's own login form (not this app's UI) → authenticate → redirected back and land in the app already signed in. Four scenarios, each its own top-level `test()` (not `test.step`s sharing one browser context — Keycloak's own SSO session persisted across steps otherwise, silently reusing the first user's login for the second): (1) `sso-admin` provisions an account and gets the `org_admin` role its Keycloak group maps to; (2) a user in an unmapped Keycloak group gets an account but zero organisation role; (3) with `oidc_required_group` set, `sso-member` (outside the required group) is shown "Your organisation has not provisioned you access" and never receives a session token; (4) with the same gate set, `sso-admin` (inside the required group) still gets in.
- **Expected outcome:** all four confirmed against a real IdP round trip, not mocked — the resulting account's role is checked via the API afterward in each case.

## Full-product coverage pass

A follow-up round, driven by a "review the whole product like a QA lead" request: cross-check every page/workflow in the app against `docs/requirements.md` and `docs/decisions.md`, and close whatever Playwright gaps remain. Murchison (v4)/SCIM/separate-provisioning-port items were skipped as not-yet-built, per prior decisions. Same discipline as workflows 1–7 above: real UI interaction as the primary path, a direct API call to prove server-side enforcement wherever a permission or workflow-state rule is involved.

### 8. Requirement review scheduling
**Personas:** Org Admin AlphaBeta (PM), Stakeholder Alpha, Member AlphaBeta. **Spec:** `review-scheduling.spec.ts` (C-R-06–C-R-10).

PM schedules a review (date/lead-time/reviewer) on a fresh requirement; the assigned reviewer sees it on both their personal (`/my-reviews`) and the project's (`/projects/:id/reviews-due`, filterable by component/reviewer) due lists; recording an outcome is gated to the reviewer or a PM (403 for a plain member, proven via direct API) and a `failed` outcome requires a comment (400 via direct API); recording `met` drops it off both due lists.

### 9. Change-request tasks and stakeholder voting
**Personas:** Org Admin AlphaBeta (PM), Member AlphaBeta, Stakeholder Alpha + Alpha2. **Spec:** `change-request-tasks-and-voting.spec.ts` (C-R-02–C-R-04).

PM adds a task (a plain member's attempt 403s server-side); a task assigned to a non-PM stakeholder (assignment only reachable via a direct API call today — see gap below) can be toggled done by that assignee alone; two stakeholders cast opposing advisory votes with comments, visible in a "View comments" pop-up; a direct API fetch of the CR confirms voting never touches `status`, matching the separation-of-duties guarantee from workflow 5.

### 10. Stage review deadlines and completion
**Personas:** Org Admin AlphaBeta (PM), Stakeholder Alpha, Member AlphaBeta. **Spec:** `stage-review-and-completion.spec.ts` (C-R-05, C-P-02, C-P-03).

Full stage lifecycle: scoping → PM starts review and sets a deadline → a plain member's direct-API approve attempt 403s → a stakeholder responds through the real UI → PM approves (locks requirements, writes a baseline) → a locked requirement is marked completed directly (no change request needed) and reverted → PM completes the stage with `cascade_to_requirements`, which also completes its still-approved requirements.

### 11. Project Admin: structural rename/delete/archive
**Persona:** Org Admin AlphaBeta (PM). **Spec:** `project-admin-structural.spec.ts` (C-G-07, C-E-01/02, C-P-01).

Builds its own component/category tree on Beta-2 to control the reassignment scenarios: deleting a component with categories is blocked in the UI; deleting a category reassigns whatever it governed, both within and across components; an emptied component can then be deleted; a stage with an approved baseline cannot be deleted even with a reassignment target picked (refused outright — a baseline is immutable history), but a stage with no baseline can be; the project itself can be archived then unarchived.

### 12. Project Admin: custom fields, groups, and terminology
**Persona:** Org Admin AlphaBeta (PM). **Spec:** `project-admin-groups-and-fields.spec.ts` (C-C-01/02, C-U-11).

Creates one custom field of each of the four types (short text, long text, checkbox, list) and confirms they appear on the requirement create form; deletes one; adds and removes a project group member; sets and then reverts a terminology override, confirming the nav itself relabels (e.g. "Requirements" → "Specs").

### 13. Org report templates and project report setup
**Personas:** Org Admin Gamma (single-org). **Spec:** `project-admin-templates-and-reports.spec.ts` (R-G-05, C-E-04/05).

Creates, edits, and deletes an org report template (accent colour, cover page/logo toggles, footer, chapter-per-component default); selects it as a project's default (pre-populates the Reports page); marks a project as usable as a template and confirms it appears in "New project"'s create-from-template list.

### 14. Org security controls: org-wide 2FA, display-name lock, member filters, external invites
**Persona:** Org Admin Gamma. **Spec:** `org-security-controls.spec.ts` (the "28-item batch" round, C-A-13).

Member-directory filters (stale/no-2FA/no-project-access); lock/unlock a display name; enabling org-wide 2FA blocks the admin's *own* project and settings access (proven both via UI and a direct API call against the specific project — the cross-org project *list* deliberately isn't gated the same way) until they self-enrol via Preferences (which isn't org-scoped) — then the requirement is turned back off and personal 2FA disabled again, restoring plain login; setting `external_user_policy` to "anyone" and inviting a not-yet-existing email by address.

### 15. Two-factor authentication enrollment
**Persona:** Orphan candidate. **Spec:** `two-factor-auth.spec.ts` (C-U-14).

Enrols via the real UI (the TOTP secret is captured from the `/auth/2fa/enroll` response itself, not parsed out of the rendered QR image, then used to compute real codes with `helpers.ts`'s own RFC 6238 implementation); logging back in now requires a second, code-entry step (a stale/wrong code is rejected first); disabling 2FA is proven to invalidate the current session immediately (see gap below), after which login is single-step again.

### 16. Server-admin user directory: orphaned accounts, deactivation, bans
**Persona:** Server Admin (zero orgs), Org Admin AlphaBeta. **Spec:** `user-directory-and-bans.spec.ts` (C-A-13, the "28-item batch" round).

The orphaned-accounts view is server-admin-only (403 for a non-admin via direct API) and tenant-blind; deactivate then reactivate an orphaned account (the default listing excludes deactivated accounts — a checkbox reveals them); ban it (`window.confirm` guard); a banned account can't be granted a fresh org role even via direct API (403); unban restores that ability.

### 17. Notifications page and favourites page
**Persona:** Org Admin AlphaBeta. **Spec:** `notifications-and-favourites.spec.ts` (C-N-01/02).

Generates a real notification (subscribe + comment), then exercises the dedicated `/notifications` page: search, an unread-only filter, and "mark all read". Favourites a project from the list page and confirms it appears (and can be removed) on the dedicated `/favourites` page — navigated to directly rather than via the nav link, since that link's visibility is only rechecked on arrival at `/projects`/`/favourites`, not on the favourite action itself (see gap below).

### 18. Project history / changes-over-time view
**Persona:** Org Admin AlphaBeta. **Spec:** `project-history.spec.ts` (C-A-10).

Comments are excluded from the timeline by default and only appear when "Include discussion comments" is checked; a future date-range filter shows "No changes in this range"; an entity-type filter narrows the list without erroring.

### 19. Comment editing and attachments
**Personas:** Stakeholder Alpha, Stakeholder Alpha2. **Spec:** `comment-editing-and-attachments.spec.ts` (the "comment editing/attachment redesign" round).

Posts a comment with an attachment on a *locked* requirement (comment attachments are exempt from the C-G-12 lock, unlike direct requirement attachments, which show a locked notice instead of an upload control); a different user has no Edit control and the API 403s a hijack attempt; the author edits their own comment (new body, one attachment added, one removed).

### 20. CSV import wizard
**Persona:** Org Admin AlphaBeta (PM). **Spec:** `csv-import-wizard.spec.ts`.

Uploads a CSV with non-canonical headers, maps each column manually (no auto-match), previews the mapped rows, then imports — one row succeeds, one deliberately references a non-existent component prefix and is reported as a per-row error, not a whole-import failure.

### 21. Requirements list filters and view-mode persistence
**Persona:** Org Admin AlphaBeta. **Spec:** `requirements-and-cr-filters.spec.ts` (U-E-01).

Search narrows by name substring, by unique ID, and shows an empty state for no match; status and category filters narrow the list; has-comments/only-watched checkboxes toggle without erroring; switching to list view persists across a reload (synced server-side). `badge-filters.spec.ts` already covers the status-badge click-to-filter interaction specifically.

### 22. Preferences: theme, pronouns, landing page mode; help page
**Persona:** Org Admin AlphaBeta. **Spec:** `preferences-and-theme.spec.ts` (U-U-01, C-U-18, U-U-03).

Theme persists across a reload; pronouns save and persist; all three landing-page-after-login modes (a specific project, the project list, automatic) are proven by actually logging out and back in for each — the preference is only resolved at the moment of login, not applied to ordinary in-app navigation like the brand logo (see gap below). The Help page is checked here as a light page visit rather than earning its own spec file.

### 23. Terminology overrides reach their own surfaces
**Persona:** Org Admin AlphaBeta. **Spec:** `terminology-coverage.spec.ts` (C-C-03).

Uses the dedicated Delta-1 project (see "Personas" above), seeded with a permanent `stage`/`requirement`/`change_request` override, to prove the override reaches surfaces beyond the nav label + list-page heading it already worked on before this fix: the requirement detail page's "Make a change request" link, Project Admin's custom-fields entity-kind dropdown (the 2026-08 UX audit's single most visible example — it used to read "Requirement"/"Change request" literally, one tab over from the Terminology settings meant to rename those exact words), and the project's review-due list heading. `project-admin-groups-and-fields.spec.ts` (#12 above) separately proves the *save flow* itself (set-then-revert on Beta-2); this spec is about *consumption*, not the save mechanism.

### 24. Admin page titles show their own entity's name; a version footer; "My organisations" stays personal for a server admin
**Personas:** Org Admin AlphaBeta, E2E Server Admin Only. **Specs:** `admin-page-titles-and-version-footer.spec.ts`, plus one new test added to `org-admin-nav-link.spec.ts` (#no separate number — same nav-rail link the existing test there already covers).

Three small gaps from a first-pass UX review of the audit's own fixes, not new workflows in their own right. `GET /orgs` (no `mine`) deliberately returns every org on the deployment for a server admin (I-M-05's platform-wide console view) — right for `ServerOrganisationsPage`, wrong for the nav rail's personal "My organisations" link, which called it unfiltered and so showed a server admin the entire server's org list regardless of their own membership; fixed by switching to `GET /orgs?mine=true` (the same opt-out `ProjectListPage`'s own org filter already uses), proven with the zero-membership `e2e-serveradmin@example.com` persona seeing the empty state instead. Separately, Org Admin's resource-menu restructure (#entry above, "Org Admin -> resource-menu restructure" in `docs/decisions.md`) left the organisation's name visible only on the Overview group's own content — every other group had no page title at all; Project Admin's `<h1>` was the generic "{Project} admin" label with no project name anywhere. Both fixed by giving `ResourceMenu` a `title`/`subtitle` (Org Admin) and swapping Project Admin's own `<h1>` to the project's name, proven by checking the heading persists after switching groups, not just on first load. Unrelated to page titles: a new nav-rail footer shows the frontend and backend's own build versions (`GET /api/v1/system/version`), checked here for presence/format only, since this dev/test stack's images carry no real build ARGs.

### 25. Hierarchical (parent/child) projects
**Personas:** Org Admin Gamma, Project manager (no org role). **Spec:** `project-hierarchy.spec.ts` (docs/decisions.md's "Hierarchical projects" entry).

Four tests, using the fixed Gamma-3/Gamma-4 pair plus dynamically-created projects: (1) create a sub-project via the create modal, confirm `MIRROR_ALL` requires — and a cancel correctly declines — a confirmation naming the parent, confirm "Child of:"/"Parent of:" labels and the tree view render the resulting pair, and confirm "Add sub-project" from a project's own admin page pre-fills the parent in the create modal; (2) the parent's admin page lists a child as a member source while the child's own admin page has no way to manage that relationship, effective members shows a forward-inherited user's provenance, and "Convert all inherited access to direct roles" converts it (reverted via a direct API call at the end of the test so the fixture stays idempotent across repeated runs — materializing is a one-way, permanent grant); (3) the no-org-role project manager persona creates a sub-project of a project they manage via the relaxed path, cannot detach it (`parent_required`) until granted `project_creator`, then can; (4) an org admin disables the relaxed-creation toggle, blocking the same persona's "Add sub-project", then restores it for later runs.

Two real, user-facing bugs were found only by running this against the live stack, not by any static check — see docs/decisions.md's entry for the full account: the create modal's parent-selector excluded the very project being selected as parent (so a pre-filled "Add sub-project" parent could never actually display as chosen), and the new "Effective members" section's title collided with every project's default "Members" group, breaking an unrelated pre-existing spec's `openGroupCard` helper.

## Product gaps found

- **No self-service "leave an organisation" existed anywhere in the product — now fixed.** Confirmed by reading every route in `backend/app/routers/orgs.py` — there was no endpoint that removed a `UserOrgRole`. The zero-org server-admin persona above originally had to be constructed by deleting that one row directly via SQL in the seed script. Closed with a new `DELETE /api/v1/orgs/{organization_id}/membership` self-service endpoint plus a "Leave organisation" button on the Org Admin page (`frontend/src/pages/OrgAdminPage.tsx`). It refuses (409) rather than silently reassigning anyone's roles if leaving would strip the org of its last `org_admin`, or leave any of its projects with zero managers — see `backend/tests/test_rbac.py`'s `test_sole_org_admin_cannot_leave` / `test_sole_project_manager_cannot_leave_even_with_a_co_admin` for both guards, and `test_plain_member_can_leave_organization` for the happy path. The seed script now calls this endpoint on itself for the zero-org persona instead of touching SQL at all — the only remaining direct-DB step in the whole suite has been removed.
- **Change-request Approve/Reject controls were shown to any viewer, regardless of role (fixed).** `ChangeRequestDetailPage` rendered the decision controls whenever a CR's status was `submitted`/`in_review`, with no client-side check that the *viewer* actually held `project_manager`. The backend already correctly 403s the action, but a control that fails on click isn't a working workflow — a stakeholder viewing their own submitted CR would have seen Approve/Reject buttons they could never use. Fixed by adding `frontend/src/hooks/useMyProjectRoles.ts` and gating the controls on it.
- **Requirement Archive, and the editable-vs-read-only form, had the same gap (fixed).** `RequirementDetailPage` showed the Archive button to any project member regardless of role, and rendered the *editable* form (not just the locked-read-only one) to any viewer with no edit rights, purely based on the requirement's own lock state. Fixed with the same role hook: Archive requires PM/administrator; the editable form requires PM/administrator/stakeholder, matching the backend's actual gates.
- **This permission-visibility pattern (controls shown regardless of the viewer's actual role, relying entirely on server-side 403 enforcement) likely exists more broadly** — e.g. the Requirements list's "New Requirement" button, and Project Admin's component/category/custom-field forms, aren't role-gated client-side either. The two instances above were fixed because this suite's own workflows exercise them directly; a systematic pass across the rest of the app is worth doing separately rather than as a side effect of this suite.
- **Two pre-existing Playwright specs (`golden-path.spec.ts`, `mockup-engagement.spec.ts`) had latent selector/race-condition bugs, newly exposed rather than newly introduced.** The Activity Panel feature added earlier in this project's history introduced new "Server Administrator approved" / "... created" text that collided with those specs' loose `getByText("approved")` / `getByText("Server Administrator")` selectors — fixed with `exact: true`. Separately, both specs (and two of this suite's own early drafts) had a real race condition: a change-request/requirement creation form's dropdown default (first requirement, first component) populates asynchronously, and a fast `fill()` + `click()` sequence can submit before it resolves, sending an empty foreign key and silently failing server-side validation. Fixed everywhere it was found by waiting for the dropdown's expected default text before proceeding.

### From the full-product coverage pass

- **No UI path existed to put a project stage into "review" status at all — now fixed.** `ProjectAdminPage.tsx`'s only stage-transition action ("Approve stage") jumped `scoping → approved` directly; the review-deadline/stakeholder-response UI (C-R-05) only ever renders once a stage is *in* `review`, which nothing in the product could reach. Confirmed with the user before fixing (flagged as exactly the kind of gap this project's standing instructions require querying rather than silently working around). Fixed with a new "Start review" button/action, plus (the user's explicit second ask) real state-machine validation on `POST /stages/{id}/transition` — a stage can no longer skip a step (`scoping → approved` directly) or move backwards (`approved → scoping`); `COMPLETED` remains reachable only via the dedicated `/complete` endpoint. New backend test `test_stage_transition_rejects_skipping_and_backwards_moves`; four pre-existing backend tests that relied on the old direct-jump behaviour updated to go through `review` first.
- **`GET /projects/{id}/report-config` was gated to manager-only access, silently breaking the Reports page for stakeholders/members (fixed).** Discovered because a stakeholder's Project Admin page hung forever on its loading spinner — the same failure class as the previously-documented "OrgAdminPage hung forever" bug: one over-privileged fetch inside a page's single `Promise.all` reload fails the whole thing. The deeper issue: `ReportsPage.tsx` fetches this same endpoint, and per C-U-03 stakeholders/members can generate reports — so it was already silently 403ing there too, independent of the admin-page symptom that surfaced it. Fixed by loosening the GET to `require_project_view` (the PUT stays manage-only); new backend test `test_report_config_is_readable_by_a_plain_stakeholder_not_just_a_manager`.
- **`ToggleSwitch` didn't stop click propagation, breaking 2FA enrollment specifically (fixed).** `CollapsibleSection` always wraps its own title in a clickable header; `PreferencesPage.tsx`'s "Enable 2FA" toggle is the one place a `ToggleSwitch` renders *inside* that title (nested native `<button>`s). Clicking it correctly started enrollment but the click also bubbled up and collapsed the section, immediately hiding the QR code/confirmation-code UI the toggle had just revealed. Fixed with `e.stopPropagation()` in `ToggleSwitch.tsx` itself (not just the one call site), since the same nesting could recur elsewhere.
- **Disabling 2FA (and, unchanged but newly exercised here, changing password) invalidates the current session immediately — by design, not a bug, but worth stating plainly.** Both bump `token_version` server-side, and the frontend's existing `AUTH_UNAUTHORIZED_EVENT` handling logs the session out on its very next request. A test (or a real user) expecting to see an updated "Not enabled" badge in place, rather than a redirect to `/login`, will be surprised — `two-factor-auth.spec.ts` and `org-security-controls.spec.ts` both log back in afterward rather than asserting in-place UI state.
- **The "Favourites" nav link's visibility can lag a favourite/unfavourite action taken on the *same* page.** `Layout.tsx` deliberately only rechecks whether any project is favourited on arrival at `/projects` or `/favourites` (a documented tradeoff against re-checking on every route change) — toggling a favourite while already sitting on `/projects` doesn't trigger that recheck. Not fixed (the tradeoff is intentional and the workaround — navigate directly rather than via the nav link — is trivial), but worth knowing if this surprises a future spec.
- **The post-login "landing page" preference (U-U-03) only takes effect at the moment of login (`resolveLandingPath` in `LoginPage.tsx`), never on ordinary in-app navigation** (e.g. clicking the brand logo, which always goes to plain `/projects`). Not a bug — this matches the requirement's own wording ("first page seen after login") — but an easy assumption to get wrong when testing it; `preferences-and-theme.spec.ts` logs out and back in for each of the three modes rather than navigating around within one session.
- **`ChangeRequestTask` has no UI picker for `assignee_id` or `due_date` at all**, despite C-R-02/C-R-04 describing assignable tasks with due dates and the backend fully supporting both (a task's own assignee may toggle `is_done` without manager rights). The "New task" form on `ChangeRequestDetailPage.tsx` only collects a free-text description. `change-request-tasks-and-voting.spec.ts` proves the assignee-only-toggle guarantee by assigning via a direct API call (the only way to set it today) and then toggling through the real UI as that assignee — not itself a bug fix, since the backend behaves correctly, but a real product gap worth closing in a future round.
- **Two of this pass's own specs surfaced a shared architectural gap: list-fetching effects with no request-cancellation guard.** Both `ProjectHistoryPage.tsx` and `RequirementsPage.tsx` fire a fresh fetch on every filter-state change with no `AbortController`/staleness check, so two changes made in quick succession can have their responses resolve out of order, letting an older (pre-change) response overwrite a newer one. Not fixed at the architecture level (a broader change across every filtered-list page, out of scope for this pass) — worked around in both new specs by waiting for each filter change to fully settle before making the next one, the same pattern this codebase already uses for the dropdown-default races noted above.

### Full-suite hardening: cross-spec state pollution, not app bugs

Every spec above passed individually against its own fresh reseed while being written. Running the *entire* suite (all 38 specs, `workers: 1`, sequential) back-to-back against one continuously-mutating database surfaced a second class of failure that individual runs can't catch: specs whose assumptions only hold on a pristine, single-spec-touched database. None of the following were product bugs — all were fixed in the specs themselves:

- **Two specs hard-coded HW-FN-001's original name** (`comment-editing-and-attachments.spec.ts`, `project-history.spec.ts`, and the search-by-name-substring half of `requirements-and-cr-filters.spec.ts`), but `change-request-approval-separation.spec.ts` (pre-existing, runs earlier in file order) legitimately renames HW-FN-001 via a real approved change request — that's the whole point of that spec. A requirement's `name` is exactly the field CRs are designed to change; its `unique_code` is the actually-stable identifier. Fixed with a new `openRequirementByCode()` helper in `helpers.ts` that locates a requirement's row/card by code rather than name, and by retargeting the filter spec's substring-search example at a requirement no other spec touches.
- **`notifications-and-favourites.spec.ts`'s favourite toggle raced `Locator.count()` against the page's own post-navigation data fetch.** `page.goto("/projects")` only waits for navigation, not for `ProjectListPage`'s async `reload()` to populate `projects` state — so a `.count()` called immediately after `goto` (unlike `expect(...).toBeVisible()`, `.count()` doesn't auto-retry) can read 0 while the list is still loading, silently skipping the favourite click entirely. Fixed by waiting for the target card's visibility before touching `.count()`. A second, smaller race in the same step (navigating to `/favourites` without waiting for the favourite PUT to actually land) was fixed with `page.waitForResponse`.
- **`project-admin-structural.spec.ts` filled a newly-created component's category-name fields by fixed index (`.nth(3)`) immediately after clicking "New component", before that component's row had rendered** — Playwright resolved the index against the *pre-creation* DOM (4 "Name" fields, not yet 5) and silently filled the wrong (bottom, "add component") field instead, leaving the real target's "New category" button permanently disabled. Fixed by waiting for the new component's row to appear before computing the index-based locators, matching the wait the Firmware component (created just above it) already had.
- **`workflow-bypass-attempts.spec.ts` checked `Locator.count()` for "Approve stage" immediately after clicking "Start review"**, before the page re-rendered with the stage's new `review` status — the count read 0, the approval click was silently skipped, and the stage was left stuck in `review` for the rest of the test (and, since nothing else resets it, every subsequent run). Fixed by waiting for the "In review" status text before checking for the Approve button.
- **`project-admin-templates-and-reports.spec.ts` used an unscoped, non-exact `getByPlaceholder("Name")`.** Without `exact: true` it substring-matches "SMTP username" (an unrelated field elsewhere on the same Org Admin page); and even with `exact: true`, several *other* sections on that page (Add member, Add group) also have their own exactly-"Name"-placeholder field — sections that stay expanded server-side per-user once opened, including by `org-security-controls.spec.ts` sharing the same Gamma admin persona and running earlier. Fixed by scoping every "Name" field lookup to the Report Templates section's own container.
- **`preferences-and-theme.spec.ts` clicked "Save preferences" and immediately reloaded or logged out**, four separate times, racing the async `PATCH /auth/me/preferences` against the navigation that followed it. Fixed with `page.waitForResponse` on the preferences PATCH before every reload/logout in that spec.
- **`badge-filters.spec.ts` (pre-existing) logs in as `demo.admin@example.com`, from `seed_demo_data.py` — a script this suite's own documented "clean slate" recipe never ran.** Not a spec bug; the recipe in this doc's "How to run it" section was incomplete. Fixed by adding the `seed_demo_data.py` step there.
- **`seed_demo_data.py` itself broke** against the stage-transition state-machine hardening from earlier in this pass (see "No UI path existed to put a project stage into review" above) — it tried to jump Falcon-3's Scoping stage `scoping → approved` directly, which the backend now rejects (409). Fixed by adding the intermediate `review` transition, the same fix already applied to the affected backend pytest files.

**A methodology note for next time:** confirming a fix by re-running the full suite again *without* a fresh reseed in between doesn't work — the first re-run attempt here showed 9 failures in specs that had never failed before, entirely because two prior runs plus some manual browser-based debugging had left the shared database in states those specs never anticipated. The only valid verification is a full clean-slate reseed followed by exactly one suite run.

## Files

- `backend/scripts/seed_e2e_dataset.py` — the seed script.
- `tests/playwright/tests/e2e-workflows/helpers.ts` — persona/org/project constants and a shared `loginAs`/`logout`.
- `tests/playwright/tests/e2e-workflows/*.spec.ts` — one spec per workflow above.
- `tests/container/keycloak/realm-export.json` — the SSO workflow's own seed data (realm, client, and the two Keycloak-native test users), separate from `seed_e2e_dataset.py` since these users are provisioned by Keycloak itself, not this app's API.
- `frontend/src/hooks/useMyProjectRoles.ts` — the role-visibility fix used by two of the specs above.
- `backend/app/routers/orgs.py`'s `leave_organization` + `frontend/src/pages/OrgAdminPage.tsx`'s "Leave organisation" button — the self-service leave-org feature built to close the gap this suite found; tested in `backend/tests/test_rbac.py`.
- From the full-product coverage pass: `frontend/src/pages/ProjectAdminPage.tsx`'s "Start review" action + `backend/app/routers/projects.py`'s `_ALLOWED_STAGE_TRANSITIONS` (stage state-machine validation, `backend/tests/test_api_lifecycles.py::test_stage_transition_rejects_skipping_and_backwards_moves`); `report-config`'s permission fix in the same router file (`backend/tests/test_reports.py::test_report_config_is_readable_by_a_plain_stakeholder_not_just_a_manager`); `frontend/src/components/ToggleSwitch.tsx`'s `stopPropagation` fix.
