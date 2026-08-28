import { expect, test } from "@playwright/test";

import { ensureExpanded, loginAs, PERSONAS, PROJECT_NAMES, selectOrgAdminGroup, selectProjectAdminGroup } from "./helpers";

/**
 * Job to be done: an org admin defines a reusable report template (accent
 * colour, cover page/logo toggles, footer, chapter-per-component default —
 * R-G-05), a project can select it as its default (used to pre-populate
 * the report generation page), and a project can be marked usable as a
 * template for future project creation (C-E-04).
 *
 * Uses Gamma (single-org admin, `/orgs` redirects straight to its admin
 * page) to stay isolated from the Alpha/Beta specs in this suite.
 */

test.describe("org report templates and project report setup", () => {
  test("create/edit/delete an org report template, select it as a project default, mark a project as a template", async ({
    page,
  }) => {
    const templateName = `E2E Corporate Template ${Date.now()}`;

    await loginAs(page, PERSONAS.orgAdminGamma.email);
    await page.goto("/orgs");
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);

    // Scoped to the Report templates section itself, not the whole page —
    // other CollapsibleSections within the same "Templates & reports"
    // resource-menu group (2026-08 UX audit's Org Admin restructure) can be
    // left expanded/collapsed server-side by an earlier spec sharing this
    // same Gamma admin persona, and "Report Defaults" — the other section
    // in this group — has its own "Name"-adjacent fields too. A page-wide,
    // unscoped query is a strict-mode violation waiting to happen whenever
    // that section is already open. (Sections in *other* resource-menu
    // groups, e.g. "Organisation users" or "SMTP & email", are unmounted
    // entirely while this group is selected, so they're no longer a
    // concern here the way they were before the restructure — but the
    // scoping is still worth keeping for the sibling section that remains.)
    const reportTemplatesSection = page.locator(".card", {
      has: page.getByRole("button", { name: "Report templates section" }),
    });

    await test.step("create a report template", async () => {
      // Report templates moved into the "Templates & reports" resource-menu
      // group (2026-08 UX audit's Org Admin restructure) — a real
      // navigation, so it must be selected before the section is reachable
      // at all.
      await selectOrgAdminGroup(page, "Templates & reports");
      await ensureExpanded(page, "Report templates");
      // The create/edit form itself opens in a `Modal`, not inline within
      // the section (2026-08 UX audit roadmap item 526, "Modal conversion
      // sweep") — portalled to `document.body`, so it's queried from
      // `page`, not scoped to `reportTemplatesSection`.
      await reportTemplatesSection.getByRole("button", { name: "New template" }).click();
      const createDialog = page.getByRole("dialog", { name: "New template" });
      await createDialog.getByPlaceholder("Name", { exact: true }).fill(templateName);
      await createDialog.getByLabel("Include cover page").check();
      await createDialog.getByLabel("Include organisation logo").check();
      await createDialog.getByPlaceholder("Footer text").fill("Confidential — E2E Gamma Labs");
      await createDialog.getByLabel("Chapter per component by default").check();
      await createDialog.getByRole("button", { name: "Create", exact: true }).click();
      await expect(createDialog).not.toBeVisible();
      await expect(reportTemplatesSection.getByText(templateName)).toBeVisible();
    });

    const revisedName = `${templateName} (Revised)`;
    await test.step("edit the template", async () => {
      const row = reportTemplatesSection.locator(".row", { hasText: templateName }).first();
      await row.getByRole("button", { name: "Edit" }).click();
      const editDialog = page.getByRole("dialog", { name: "Edit template" });
      await editDialog.getByPlaceholder("Name", { exact: true }).fill(revisedName);
      await editDialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(editDialog).not.toBeVisible();
      await expect(reportTemplatesSection.getByText(revisedName)).toBeVisible();
    });

    await test.step("select it as Gamma-1's default report template", async () => {
      // Org Admin's own "Projects" section is management-only (user
      // access), not a navigation link — go via the real Projects list.
      await page.goto("/projects");
      await page.getByText(PROJECT_NAMES.gamma1).click();
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await selectProjectAdminGroup(page, "Report Setup");
      await page.getByLabel("Default report template").selectOption({ label: revisedName });
      // Wait for the save's own PUT to actually land before reloading — a
      // bare click() races the async `saveReportConfig()` against the
      // immediate reload below, which can reload before the request even
      // reaches the server and read the pre-save state back (same fix
      // `preferences-and-theme.spec.ts`'s "pronouns save and persist" step
      // and `requirements-and-cr-filters.spec.ts`'s view-mode-persistence
      // step already use for this identical race).
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/report-config") && r.request().method() === "PUT"),
        page.getByRole("button", { name: "Save settings" }).click(),
      ]);
      await page.reload();
      await selectProjectAdminGroup(page, "Report Setup");
      await expect(page.getByLabel("Default report template")).toHaveValue(/.+/);
    });

    await test.step("the selected default is pre-selected on the report generation page", async () => {
      await page.getByRole("link", { name: "Reports", exact: true }).click();
      await expect(page.getByText("Template & layout")).toBeVisible();
    });

    await test.step("delete the template", async () => {
      await page.goto("/orgs");
      await selectOrgAdminGroup(page, "Templates & reports");
      await ensureExpanded(page, "Report templates");
      const row = page.locator(".row", { hasText: revisedName }).first();
      await row.getByRole("button").last().click();
      await expect(page.getByText(revisedName)).toHaveCount(0);
    });

    await test.step("mark Gamma-2 as usable as a project template", async () => {
      await page.goto("/projects");
      await page.getByText(PROJECT_NAMES.gamma2).click();
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await page.getByLabel("Usable as a project template").check();
      await page.getByRole("button", { name: "Save settings" }).click();
      await page.reload();
      await expect(page.getByLabel("Usable as a project template")).toBeChecked();

      await page.getByRole("link", { name: "Projects", exact: true }).click();
      // "New project" opens a Modal (style guide "Pattern: modal dialog for
      // entity create/rename") — scoped to it rather than the whole page.
      await page.getByRole("button", { name: "New project" }).click();
      const dialog = page.getByRole("dialog", { name: "New project" });
      // Scoped to the template picker specifically — the "Parent project"
      // field (hierarchical projects) also lists every non-archived project
      // in the org as an option now, so an unscoped option-text match would
      // find Gamma-2 twice.
      await expect(dialog.getByLabel("Create from template").locator("option", { hasText: PROJECT_NAMES.gamma2 })).toHaveCount(1);
    });
  });
});
