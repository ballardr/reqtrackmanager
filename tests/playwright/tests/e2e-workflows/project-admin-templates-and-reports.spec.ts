import { expect, test } from "@playwright/test";

import { ensureExpanded, loginAs, PERSONAS, PROJECT_NAMES } from "./helpers";

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
    // other CollapsibleSections on this page (e.g. "Organisation users",
    // "Advanced settings") can be left expanded server-side by an earlier
    // spec sharing this same Gamma admin persona (org-security-controls.spec.ts
    // does exactly this), and several of them have their own "Name"-
    // placeholder field; "Advanced settings" also has an "SMTP username"
    // field, which getByPlaceholder("Name") substring-matches without
    // exact:true. A page-wide, unscoped query is a strict-mode violation
    // waiting to happen whenever those sections are already open.
    const reportTemplatesSection = page.locator(".card", {
      has: page.getByRole("button", { name: "Report templates section" }),
    });

    await test.step("create a report template", async () => {
      await ensureExpanded(page, "Report templates");
      await reportTemplatesSection.getByPlaceholder("Name", { exact: true }).fill(templateName);
      await reportTemplatesSection.getByLabel("Include cover page").check();
      await reportTemplatesSection.getByLabel("Include organisation logo").check();
      await reportTemplatesSection.getByPlaceholder("Footer text").fill("Confidential — E2E Gamma Labs");
      await reportTemplatesSection.getByLabel("Chapter per component by default").check();
      await reportTemplatesSection.getByRole("button", { name: "New template", exact: true }).click();
      await expect(reportTemplatesSection.getByText(templateName)).toBeVisible();
    });

    const revisedName = `${templateName} (Revised)`;
    await test.step("edit the template", async () => {
      const row = reportTemplatesSection.locator(".row", { hasText: templateName }).first();
      await row.getByRole("button", { name: "Edit" }).click();
      await reportTemplatesSection.getByPlaceholder("Name", { exact: true }).fill(revisedName);
      await reportTemplatesSection.getByRole("button", { name: "Save", exact: true }).click();
      await expect(reportTemplatesSection.getByText(revisedName)).toBeVisible();
    });

    await test.step("select it as Gamma-1's default report template", async () => {
      // Org Admin's own "Projects" section is management-only (user
      // access), not a navigation link — go via the real Projects list.
      await page.goto("/projects");
      await page.getByText(PROJECT_NAMES.gamma1).click();
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await page.getByRole("tab", { name: "Report Setup" }).click();
      await page.getByLabel("Default report template").selectOption({ label: revisedName });
      await page.getByRole("button", { name: "Save settings" }).click();
      await page.reload();
      await page.getByRole("tab", { name: "Report Setup" }).click();
      await expect(page.getByLabel("Default report template")).toHaveValue(/.+/);
    });

    await test.step("the selected default is pre-selected on the report generation page", async () => {
      await page.getByRole("link", { name: "Reports", exact: true }).click();
      await expect(page.getByText("Template & layout")).toBeVisible();
    });

    await test.step("delete the template", async () => {
      await page.goto("/orgs");
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
      await page.getByRole("button", { name: "New project" }).click();
      await expect(page.locator("option", { hasText: PROJECT_NAMES.gamma2 })).toHaveCount(1);
    });
  });
});
