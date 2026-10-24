import { expect, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup, setOrgModuleAvailability, showLinkRelationships, recordCodeText } from "../../e2e-workflows/helpers";
import { selectLabeledOption } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API_BASE_URL = "http://localhost:8000";

/**
 * Job to be done: Playwright e2e coverage for create -> propose ->
 * approve -> supersede, with the quick-view +
 * full-page detail split. Exercises the full Decision Management frontend
 * (`frontend/src/modules/decisions/`) against a real backend: creating a
 * Decision, moving it through its lifecycle to Approved on its own detail
 * page, then creating a second Decision that supersedes the first and
 * watching the first flip to Superseded once the second is itself Approved
 * (§13/10.6 — see `service.py`'s own `_maybe_supersede`/
 * `_supersede_predecessors`).
 *
 * A row click on the Decisions list opens `DecisionQuickViewPanel` — a
 * minimal, read-only `SidePanel` (`role="dialog"`) with no lifecycle
 * controls of its own — whose "View full details" link is what reaches
 * `DecisionDetailPage`, a real routed page (not a dialog) carrying every
 * lifecycle action, the Links panel, comments, and attachments.
 * Locators below are scoped to `page` (not a `dialog` role) once on that
 * page, unlike the earlier version of this spec.
 *
 * Uses a brand-new, disposable organisation + admin + project created via
 * the API, not a shared seeded org/project — mirrors `org-admin-modules
 * .spec.ts`'s own established reasoning (a disposable org sidesteps any
 * collision with another spec touching shared org state, and here it's
 * doubly necessary: Decision Management is `default_enabled=False`, so this
 * spec must toggle it on for whichever org it runs against, and doing that
 * against a shared org would leak into every other spec running
 * concurrently against it).
 *
 * `selectLabeledOption` (`./helpers.ts`) works around a Playwright-specific
 * `internal:label=` quirk with `LabeledSelect`'s wrapping-`<label>` markup —
 * see that helper's own docstring (mirrors `modules/compliance/helpers.ts`'s
 * `selectFilterOption`, the same underlying issue for `FilterField`).
 */
test.describe("Decision Management: create -> propose -> approve -> supersede", () => {
  test("moves a Decision through its lifecycle and supersedes it with a second, approved Decision", async ({ page }) => {
    await showLinkRelationships(page);
    const suffix = Date.now();
    const orgName = `E2E Decisions Org ${suffix}`;
    const adminEmail = `e2e-decisions-admin-${suffix}@example.com`;
    const projectName = `E2E Decisions Project ${suffix}`;

    // --- Disposable org + admin + project, via the API (server admin creates
    // the org and its first admin; that admin then creates their own project).
    const serverAdminLoginResp = await page.request.post(`${API_BASE_URL}/api/v1/auth/login`, {
      data: { email: "admin@example.com", password: "ChangeMe123!" },
    });
    const serverAdminToken = (await serverAdminLoginResp.json()).access_token;
    const serverAdminHeaders = { Authorization: `Bearer ${serverAdminToken}` };

    const org = await (
      await page.request.post(`${API_BASE_URL}/api/v1/orgs`, {
        headers: serverAdminHeaders,
        data: { name: orgName },
      })
    ).json();
    deleteOrgOnCleanup({ id: org.id });
    await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users`, {
      headers: serverAdminHeaders,
      data: { email: adminEmail, display_name: "E2E Decisions Admin", password: PASSWORD, role: "org_admin" },
    });

    await loginAs(page, adminEmail, PASSWORD);
    const adminToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const adminHeaders = { Authorization: `Bearer ${adminToken}` };

    const project = await (
      await page.request.post(`${API_BASE_URL}/api/v1/projects`, {
        headers: adminHeaders,
        data: { organization_id: org.id, name: projectName, summary: "" },
      })
    ).json();

    // --- Enable Decision Management for this org (default_enabled=False —
    // module.py's deliberate opt-in design).
    // `OrgListPage.tsx` auto-redirects straight to `/orgs/:orgId/admin`
    // when the caller belongs to exactly one org (true here — this admin
    // was just created in this one disposable org), so there's no "org
    // link" to click, unlike `org-admin-modules.spec.ts`'s own multi-org
    // server-admin persona.
    await page.goto("/orgs");
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
    await selectOrgAdminGroup(page, "Modules");
    await expect(page.getByRole("combobox", { name: "Decision Management availability", exact: true })).toHaveValue("off");
    await setOrgModuleAvailability(page, "Decision Management", "default_on");

    // --- Navigate into the project's own new "Decisions" nav entry.
    await page.goto(`/projects/${project.id}`);
    // `exact: true` — a substring match would also hit the header's own
    // user-menu link ("E2E Decisions Admin — Preferences"), since this
    // persona's own display name happens to contain "Decisions" too.
    await page.getByRole("link", { name: "Decisions", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/decisions(?:\\?.*)?$`));

    // --- Create Decision A ("DEC-001") and move it to Approved on its own
    // detail page (reached via the list's quick-view panel).
    await page.getByRole("button", { name: "New decision" }).click();
    let dialog = page.getByRole("dialog", { name: "New decision" });
    await dialog.getByLabel("Decision title").fill("Adopt PostgreSQL for the billing service");
    await dialog.getByLabel("Decision statement").fill("Use PostgreSQL as the backing store for the billing service.");
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("button", { name: "DEC-001" })).toBeVisible();

    await page.getByRole("button", { name: "DEC-001" }).click();
    let quickView = page.getByRole("dialog", { name: "DEC-001" });
    await expect(quickView.getByRole("link", { name: "View full details" })).toBeVisible();
    await quickView.getByRole("link", { name: "View full details" }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/decisions/[^/]+$`));

    await expect(page.locator(".record-header").getByText(recordCodeText("DEC-001"))).toBeVisible();
    // Scoped to the detail header: the list page's own "Draft" badges and
    // Status filter option can still be in the DOM while the route swaps.
    await expect(page.locator(".record-header").getByText("Draft", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Propose" }).click();
    await expect(page.getByText("Proposed", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Submit for review" }).click();
    await expect(page.getByText("Under review", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Approve" }).click();
    let confirmDialog = page.getByRole("dialog", { name: "Approve this Decision?" });
    await confirmDialog.getByLabel("Approval comment").fill("Agreed at the architecture board.");
    await confirmDialog.getByRole("button", { name: "Approve" }).click();
    await expect(page.getByText("Approved", { exact: true })).toBeVisible();

    // The comment given at approval is shown, quoted, in the record's own Activity tab.
    await page.getByRole("tab", { name: "Activity" }).click();
    await expect(page.locator("blockquote.activity-note", { hasText: "Agreed at the architecture board." })).toBeVisible();
    await page.getByRole("tab", { name: "Links" }).click();

    // --- Back to the list, create Decision B ("DEC-002") and move it to
    // Approved too.
    // `exact: true` and the arrow prefix disambiguate this page's own back
    // link (`DecisionDetailPage.tsx`) from the nav-rail's own "Decisions"
    // link, which also matches a plain substring search on this page.
    await page.getByRole("link", { name: "← Decisions", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/decisions(?:\\?.*)?$`));

    await page.getByRole("button", { name: "New decision" }).click();
    dialog = page.getByRole("dialog", { name: "New decision" });
    await dialog.getByLabel("Decision title").fill("Adopt Terraform for infrastructure");
    await dialog.getByLabel("Decision statement").fill("Manage infrastructure as code with Terraform.");
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("button", { name: "DEC-002" })).toBeVisible();

    await page.getByRole("button", { name: "DEC-002" }).click();
    quickView = page.getByRole("dialog", { name: "DEC-002" });
    await quickView.getByRole("link", { name: "View full details" }).click();
    // Wait for the route change itself, not just page content, before
    // querying the DOM — the list page (and its own "Superseded"/status
    // text in the table and FilterPanel) is still mounted for one render
    // tick after the `Link` click, and a bare `getByText` query racing that
    // window can hit a real Playwright strict-mode violation (multiple
    // matches) rather than a plain "not found yet" retry.
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/decisions/[^/]+$`));
    await expect(page.locator(".record-header").getByText(recordCodeText("DEC-002"))).toBeVisible();

    await page.getByRole("button", { name: "Propose" }).click();
    await page.getByRole("button", { name: "Submit for review" }).click();
    await page.getByRole("button", { name: "Approve" }).click();
    confirmDialog = page.getByRole("dialog", { name: "Approve this Decision?" });
    await confirmDialog.getByRole("button", { name: "Approve" }).click();
    await expect(page.getByText("Approved", { exact: true })).toBeVisible();

    // --- From DEC-002's Links panel, record that it supersedes DEC-001 — both
    // Decisions are already Approved, so the supersession should flip DEC-001 to
    // Superseded immediately (`_maybe_supersede`: link created after the new
    // Decision is already approved).
    await page.getByRole("button", { name: "Supersede another Decision" }).click();
    const supersedeDialog = page.getByRole("dialog", { name: "Supersede another Decision" });
    await selectLabeledOption(supersedeDialog, "Decision", "DEC-001 — Adopt PostgreSQL for the billing service");
    await supersedeDialog.getByRole("button", { name: "Supersede", exact: true }).click();
    // Scoped to the Links panel's own row — the supersession is a dedicated link,
    // so it is listed with its phrase but offers no remove control.
    const supersessionRow = page.locator(".artefact-links__phrase", { hasText: "Supersedes" });
    await expect(supersessionRow).toBeVisible();
    await expect(supersessionRow).toContainText("DEC-001");
    await expect(supersessionRow.getByRole("button")).toHaveCount(0);

    // --- DEC-001 is now Superseded — check from its own detail page.
    // `exact: true` and the arrow prefix disambiguate this page's own back
    // link (`DecisionDetailPage.tsx`) from the nav-rail's own "Decisions"
    // link, which also matches a plain substring search on this page.
    await page.getByRole("link", { name: "← Decisions", exact: true }).click();
    // The list opens on Decisions still to be made; the approved and superseded ones need the filter cleared.
    await expect(page.getByRole("checkbox", { name: "Open only" })).toBeChecked();
    await expect(page.getByRole("button", { name: "DEC-001" })).toHaveCount(0);
    await page.getByRole("checkbox", { name: "Open only" }).uncheck();
    await page.getByRole("button", { name: "DEC-001" }).click();
    quickView = page.getByRole("dialog", { name: "DEC-001" });
    await quickView.getByRole("link", { name: "View full details" }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/decisions/[^/]+$`));
    // The URL changes before the list page unmounts; until it does, its
    // quick view (also headed "DEC-001"), table badge and status filter
    // option all match too. Wait for the list's own table to go first.
    await expect(page.getByRole("table")).toHaveCount(0);
    await expect(page.locator(".record-header").getByText(recordCodeText("DEC-001"))).toBeVisible();
    await expect(page.getByText("Superseded", { exact: true })).toBeVisible();
  });
});
