# Multi-org, multi-persona end-to-end workflow suite

This document catalogues the jobs-to-be-done this suite verifies, the exact personas and credentials it uses, and how to re-run the whole thing from scratch. The suite exists to answer one question with evidence, not assertion: **do ReqTrackManager's permission boundaries and requirement-lifecycle guarantees actually hold, in the real browser UI, under realistic multi-tenant data?**

It complements the existing `tests/playwright/tests/{golden-path,pelion-v2,mockup-engagement}.spec.ts` specs, which exercise the feature set as the single bootstrap admin in one organisation. This suite instead spans three organisations, six projects, and five distinct personas whose access differs in specific, deliberate ways, plus a dedicated pass at trying to break the rules a well-behaved user would never test.

## How to run it, end to end, from a clean slate

```bash
cd tests/container
docker compose down -v && docker compose up --build -d   # fresh database
docker compose exec backend python -m pytest -q          # backend unit/integration suite

# re-bootstrap the server admin (pytest truncates all tables, including it)
docker compose restart backend

docker compose exec backend mkdir -p /app/scripts
docker compose cp ../../backend/scripts/seed_e2e_dataset.py backend:/app/scripts/seed_e2e_dataset.py
docker compose exec backend python -m scripts.seed_e2e_dataset

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
| Member, two orgs | `e2e-member-ab@example.com` | `member` in Alpha + Beta | `member` on Alpha-1 and Beta-1 | A user whose access spans two different organisations' projects, with no admin/creator rights anywhere. |

Orgs: **E2E Alpha Robotics**, **E2E Beta Software**, **E2E Gamma Labs**, two projects each (Alpha-1/2, Beta-1/2, Gamma-1/2), 6-8 requirements per project across 2 components × 2 categories, plus a couple of pre-existing change requests for volume. Alpha-1's first requirement (`HW-FN-001`) is locked (status `approved`) by the seed script specifically to give the change-request and bypass-attempt workflows something to target immediately.

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

## Product gaps found

- **No self-service "leave an organisation" existed anywhere in the product — now fixed.** Confirmed by reading every route in `backend/app/routers/orgs.py` — there was no endpoint that removed a `UserOrgRole`. The zero-org server-admin persona above originally had to be constructed by deleting that one row directly via SQL in the seed script. Closed with a new `DELETE /api/v1/orgs/{organization_id}/membership` self-service endpoint plus a "Leave organisation" button on the Org Admin page (`frontend/src/pages/OrgAdminPage.tsx`). It refuses (409) rather than silently reassigning anyone's roles if leaving would strip the org of its last `org_admin`, or leave any of its projects with zero managers — see `backend/tests/test_rbac.py`'s `test_sole_org_admin_cannot_leave` / `test_sole_project_manager_cannot_leave_even_with_a_co_admin` for both guards, and `test_plain_member_can_leave_organization` for the happy path. The seed script now calls this endpoint on itself for the zero-org persona instead of touching SQL at all — the only remaining direct-DB step in the whole suite has been removed.
- **Change-request Approve/Reject controls were shown to any viewer, regardless of role (fixed).** `ChangeRequestDetailPage` rendered the decision controls whenever a CR's status was `submitted`/`in_review`, with no client-side check that the *viewer* actually held `project_manager`. The backend already correctly 403s the action, but a control that fails on click isn't a working workflow — a stakeholder viewing their own submitted CR would have seen Approve/Reject buttons they could never use. Fixed by adding `frontend/src/hooks/useMyProjectRoles.ts` and gating the controls on it.
- **Requirement Archive, and the editable-vs-read-only form, had the same gap (fixed).** `RequirementDetailPage` showed the Archive button to any project member regardless of role, and rendered the *editable* form (not just the locked-read-only one) to any viewer with no edit rights, purely based on the requirement's own lock state. Fixed with the same role hook: Archive requires PM/administrator; the editable form requires PM/administrator/stakeholder, matching the backend's actual gates.
- **This permission-visibility pattern (controls shown regardless of the viewer's actual role, relying entirely on server-side 403 enforcement) likely exists more broadly** — e.g. the Requirements list's "New Requirement" button, and Project Admin's component/category/custom-field forms, aren't role-gated client-side either. The two instances above were fixed because this suite's own workflows exercise them directly; a systematic pass across the rest of the app is worth doing separately rather than as a side effect of this suite.
- **Two pre-existing Playwright specs (`golden-path.spec.ts`, `mockup-engagement.spec.ts`) had latent selector/race-condition bugs, newly exposed rather than newly introduced.** The Activity Panel feature added earlier in this project's history introduced new "Server Administrator approved" / "... created" text that collided with those specs' loose `getByText("approved")` / `getByText("Server Administrator")` selectors — fixed with `exact: true`. Separately, both specs (and two of this suite's own early drafts) had a real race condition: a change-request/requirement creation form's dropdown default (first requirement, first component) populates asynchronously, and a fast `fill()` + `click()` sequence can submit before it resolves, sending an empty foreign key and silently failing server-side validation. Fixed everywhere it was found by waiting for the dropdown's expected default text before proceeding.

## Files

- `backend/scripts/seed_e2e_dataset.py` — the seed script.
- `tests/playwright/tests/e2e-workflows/helpers.ts` — persona/org/project constants and a shared `loginAs`/`logout`.
- `tests/playwright/tests/e2e-workflows/*.spec.ts` — one spec per workflow above.
- `frontend/src/hooks/useMyProjectRoles.ts` — the role-visibility fix used by two of the specs above.
- `backend/app/routers/orgs.py`'s `leave_organization` + `frontend/src/pages/OrgAdminPage.tsx`'s "Leave organisation" button — the self-service leave-org feature built to close the gap this suite found; tested in `backend/tests/test_rbac.py`.
