import { expect, test } from "@playwright/test";

import { PASSWORD, loginAs, selectOrgAdminGroup } from "../../e2e-workflows/helpers";
import { selectLabeledOption } from "./helpers";

const API_BASE_URL = "http://localhost:8000";

/**
 * Job to be done: docs/plans/module-04-decision-management-plan.md Phase 5's
 * own exit criteria — "Playwright e2e coverage for create -> propose ->
 * approve -> supersede." Exercises the full Decision Management frontend
 * (`frontend/src/modules/decisions/`) against a real backend: creating a
 * Decision, moving it through its lifecycle to Approved, then creating a
 * second Decision that supersedes the first and watching the first flip to
 * Superseded once the second is itself Approved (source overview §13/10.6 —
 * see `service.py`'s own `_maybe_supersede`/`_supersede_predecessors`).
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
    // module.py's Phase 1/4 deliberate opt-in design, unchanged by Phase 5).
    // `OrgListPage.tsx` auto-redirects straight to `/orgs/:orgId/admin`
    // when the caller belongs to exactly one org (true here — this admin
    // was just created in this one disposable org), so there's no "org
    // link" to click, unlike `org-admin-modules.spec.ts`'s own multi-org
    // server-admin persona.
    await page.goto("/orgs");
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
    await selectOrgAdminGroup(page, "Modules");
    const decisionsRow = page.locator("tr", { hasText: "Decision Management" });
    await expect(decisionsRow).toBeVisible();
    const moduleToggle = decisionsRow.getByRole("switch");
    await expect(moduleToggle).toHaveAttribute("aria-checked", "false");
    await moduleToggle.click();
    await expect(moduleToggle).toHaveAttribute("aria-checked", "true");

    // --- Navigate into the project's own new "Decisions" nav entry.
    await page.goto(`/projects/${project.id}`);
    // `exact: true` — a substring match would also hit the header's own
    // user-menu link ("E2E Decisions Admin — Preferences"), since this
    // persona's own display name happens to contain "Decisions" too.
    await page.getByRole("link", { name: "Decisions", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/decisions$`));

    // --- Create Decision A ("DEC-001") and move it to Approved.
    await page.getByRole("button", { name: "New decision" }).click();
    let dialog = page.getByRole("dialog", { name: "New decision" });
    await dialog.getByLabel("Decision title").fill("Adopt PostgreSQL for the billing service");
    await dialog.getByLabel("Decision statement").fill("Use PostgreSQL as the backing store for the billing service.");
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("button", { name: "DEC-001" })).toBeVisible();

    await page.getByRole("button", { name: "DEC-001" }).click();
    let panel = page.getByRole("dialog", { name: "DEC-001" });
    await expect(panel.getByText("Draft", { exact: true })).toBeVisible();
    await panel.getByRole("button", { name: "Propose" }).click();
    await expect(panel.getByText("Proposed", { exact: true })).toBeVisible();
    await panel.getByRole("button", { name: "Submit for review" }).click();
    await expect(panel.getByText("Under review", { exact: true })).toBeVisible();
    await panel.getByRole("button", { name: "Approve" }).click();
    let confirmDialog = page.getByRole("dialog", { name: "Approve this Decision?" });
    await confirmDialog.getByRole("button", { name: "Approve" }).click();
    await expect(panel.getByText("Approved", { exact: true })).toBeVisible();
    await panel.getByRole("button", { name: "Close" }).click();

    // --- Create Decision B ("DEC-002") and move it to Approved too.
    await page.getByRole("button", { name: "New decision" }).click();
    dialog = page.getByRole("dialog", { name: "New decision" });
    await dialog.getByLabel("Decision title").fill("Adopt Terraform for infrastructure");
    await dialog.getByLabel("Decision statement").fill("Manage infrastructure as code with Terraform.");
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("button", { name: "DEC-002" })).toBeVisible();

    await page.getByRole("button", { name: "DEC-002" }).click();
    panel = page.getByRole("dialog", { name: "DEC-002" });
    await panel.getByRole("button", { name: "Propose" }).click();
    await panel.getByRole("button", { name: "Submit for review" }).click();
    await panel.getByRole("button", { name: "Approve" }).click();
    confirmDialog = page.getByRole("dialog", { name: "Approve this Decision?" });
    await confirmDialog.getByRole("button", { name: "Approve" }).click();
    await expect(panel.getByText("Approved", { exact: true })).toBeVisible();

    // --- From DEC-002's own Relationships section, record that it
    // supersedes DEC-001 — both Decisions are already Approved, so the
    // supersession should flip DEC-001 to Superseded immediately
    // (`_maybe_supersede`: link created after the new Decision is already
    // approved).
    await selectLabeledOption(panel, "Relationship", "Supersedes another Decision");
    await selectLabeledOption(panel, "Decision this supersedes", "DEC-001 — Adopt PostgreSQL for the billing service");
    await panel.getByRole("button", { name: "Add", exact: true }).click();
    // Scoped to the relationship row itself (`.row.card`,
    // `DecisionRelationshipsSection.tsx`) — a bare `getByText(/DEC-001/)`
    // also matches the still-rendered (if no longer visible) `<option>`
    // this same form's own "Decision this supersedes" `<select>` carries,
    // a Playwright strict-mode violation regardless of that option's own
    // visibility.
    const supersessionRow = panel.locator(".row.card", { hasText: "Supersedes" });
    await expect(supersessionRow).toBeVisible();
    await expect(supersessionRow).toContainText("DEC-001");
    await panel.getByRole("button", { name: "Close" }).click();

    // --- DEC-001 is now Superseded.
    await page.getByRole("button", { name: "DEC-001" }).click();
    panel = page.getByRole("dialog", { name: "DEC-001" });
    await expect(panel.getByText("Superseded", { exact: true })).toBeVisible();
  });
});
