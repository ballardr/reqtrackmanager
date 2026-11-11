import { expect, test } from "@playwright/test";

import { apiHeaders, installCleanupHook, loginAs, onCleanup, openProject, PERSONAS, PROJECT_NAMES, selectOrgAdminGroup, selectProjectAdminGroup } from "./helpers";

/**
 * Job to be done: an org admin finds the organisation's report look on Branding and Configuration, not in a list of
 * report templates (there are none), and a project can be marked usable as a template for future project creation
 * (C-E-04). A project has no default template and no report content to set.
 *
 * Uses Gamma (single-org admin, `/orgs` redirects straight to its admin
 * page) to stay isolated from the Alpha/Beta specs in this suite.
 *
 * Marks the seeded Gamma-2 project as a template, which hides it from the Projects list, so the file runs with the
 * global-state specs (one worker, before the parallel ones) and unmarks the project afterwards.
 */

const API = "http://localhost:8000/api/v1";

test.describe("org report look and project report setup", () => {
  installCleanupHook();

  test("there is no report templates section, a project has no default template, mark a project as a template", async ({
    page,
  }) => {
    onCleanup(async (request) => {
      const headers = await apiHeaders(request, PERSONAS.orgAdminGamma.email);
      const projects: { id: string; name: string }[] = await (await request.get(`${API}/projects?include_templates=true`, { headers })).json();
      const gamma2 = projects.find((project) => project.name === PROJECT_NAMES.gamma2);
      if (gamma2) await request.patch(`${API}/projects/${gamma2.id}`, { headers, data: { is_template: false } });
    });
    await loginAs(page, PERSONAS.orgAdminGamma.email);
    await page.goto("/orgs");
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);

    await test.step("Reports has no Report templates section", async () => {
      await selectOrgAdminGroup(page, "Reports");
      await expect(page.getByRole("button", { name: "Report layouts section" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Report templates section" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "New template" })).toHaveCount(0);
    });

    await test.step("a project's Report Setup has layouts and no default template or report content", async () => {
      // Org Admin's own "Projects" section is management-only (user
      // access), not a navigation link — go via the real Projects list.
      await page.goto("/projects");
      await openProject(page, PROJECT_NAMES.gamma1);
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await selectProjectAdminGroup(page, "Reports");
      await expect(page.getByRole("button", { name: "New", exact: true })).toBeVisible();
      await expect(page.getByRole("treegrid", { name: "Reports, packs and tables" })).toBeVisible();
      await expect(page.getByLabel("Default report template")).toHaveCount(0);
      await expect(page.getByLabel("Report type")).toHaveCount(0);
    });

    await test.step("the requirement report offers no template choice", async () => {
      await page.getByRole("link", { name: "Overview", exact: true }).click();
      await page.getByRole("button", { name: "Reports", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Reports" });
      await expect(dialog.getByRole("button", { name: "Generate PDF" })).toBeVisible();
      await expect(dialog.getByLabel("Report template")).toHaveCount(0);
      await expect(dialog.getByText("Template & layout")).toHaveCount(0);
    });

    await test.step("mark Gamma-2 as usable as a project template", async () => {
      await page.goto("/projects");
      await openProject(page, PROJECT_NAMES.gamma2);
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await page.getByLabel("Usable as a project template").check();
      // Same PUT-vs-reload race the "select it as Gamma-1's default report
      // template" step above already guards against: a bare click() races
      // saveSettings()'s PATCH against the immediate reload below, which
      // can reload before the request reaches the server and read the
      // pre-save (unchecked) state back.
      await Promise.all([
        page.waitForResponse((r) => r.url().includes(`/api/v1/projects/`) && r.request().method() === "PATCH"),
        page.getByRole("button", { name: "Save settings" }).click(),
      ]);
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
