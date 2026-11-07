import { expect, test } from "@playwright/test";

import {
  apiHeaders, createDisposableProject, ensureExpanded, installCleanupHook, loginAs, onCleanup, ORG_NAMES, PERSONAS, selectOrgAdminGroup,
} from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: a project manager renames a navigation entry, and the new name shows in the navigation, the
 * page title and the back link of that entry's records; restoring the name brings the built-in one back, and an
 * organisation default applies to a project that has no name of its own.
 *
 * Uses a disposable project (archived by cleanup). The organisation default set in the second test is removed in
 * its cleanup, so no other spec sees it.
 */
test.describe("navigation names", () => {
  installCleanupHook();

  test("a renamed entry shows in the navigation, the page title and the back link, and can be restored", async ({ page }) => {
    test.setTimeout(60_000);
    const email = PERSONAS.orgAdminAlphaBeta.email;
    const project = await createDisposableProject(page.request, email, "E2E Nav Names Project", ORG_NAMES.alpha);
    const headers = await apiHeaders(page.request, email);
    const requirement = await (await page.request.post(`${API}/projects/${project.projectId}/requirements`, {
      headers, data: { name: "E2E Nav Names Req", component_id: project.components[0].id, category_id: project.categories[0].id },
    })).json();
    const rail = page.locator("nav.nav-rail");

    await test.step("the project manager renames Requirements in Project Admin", async () => {
      await loginAs(page, email);
      await page.goto(`/projects/${project.projectId}/admin/overview`);
      await page.getByRole("textbox", { name: "Name for Requirements", exact: true }).fill("Needs list");
      await page.getByRole("button", { name: "Save names" }).click();
      await expect(page.getByText("Navigation names saved.")).toBeVisible();
      await expect(rail.getByRole("link", { name: "Needs list" })).toBeVisible();
    });

    await test.step("the list title and the record's back link use the new name", async () => {
      await rail.getByRole("link", { name: "Needs list" }).click();
      await expect(page.getByRole("heading", { level: 1, name: "Needs list" })).toBeVisible();
      await page.goto(`/projects/${project.projectId}/requirements/${requirement.id}`);
      await expect(page.getByRole("link", { name: "← Needs list" })).toBeVisible();
    });

    await test.step("restoring the name brings the built-in one back", async () => {
      await page.goto(`/projects/${project.projectId}/admin/overview`);
      await page.getByRole("button", { name: "Restore the default name of Requirements", exact: true }).click();
      await page.getByRole("button", { name: "Save names" }).click();
      await expect(page.getByText("Navigation names saved.")).toBeVisible();
      await expect(rail.getByRole("link", { name: "Requirements" })).toBeVisible();
      await expect(rail.getByRole("link", { name: "Needs list" })).toHaveCount(0);
    });
  });

  test("an organisation default applies to a project with no name of its own", async ({ page }) => {
    test.setTimeout(60_000);
    const email = PERSONAS.orgAdminAlphaBeta.email;
    const project = await createDisposableProject(page.request, email, "E2E Nav Default Project", ORG_NAMES.alpha);
    const headers = await apiHeaders(page.request, email);
    const orgUrl = `${API}/orgs/${project.organizationId}/nav-labels`;
    onCleanupRestoreOrgNames(orgUrl, email);

    await test.step("the organisation administrator sets a default name in Organisation Admin", async () => {
      await loginAs(page, email);
      await page.goto(`/orgs/${project.organizationId}/admin`);
      await selectOrgAdminGroup(page, "Projects & workflow");
      await ensureExpanded(page, "Navigation names");
      await page.getByRole("textbox", { name: "Name for Files" }).fill("Documents");
      await page.getByRole("button", { name: "Save names" }).click();
      await expect(page.getByText("Navigation names saved.")).toBeVisible();
    });

    await test.step("the project shows it, and a name of its own takes precedence", async () => {
      await page.goto(`/projects/${project.projectId}`);
      await expect(page.locator("nav.nav-rail").getByRole("link", { name: "Documents" })).toBeVisible();
      const own = await page.request.put(`${API}/projects/${project.projectId}/nav-labels`, { headers, data: { names: { files: "Attachments" } } });
      expect(own.ok()).toBeTruthy();
      await page.reload();
      await expect(page.locator("nav.nav-rail").getByRole("link", { name: "Attachments" })).toBeVisible();
    });
  });
});

/** Registers cleanup that clears the organisation's default names, which the test set. */
function onCleanupRestoreOrgNames(orgUrl: string, email: string): void {
  onCleanup(async (request) => {
    await request.put(orgUrl, { headers: await apiHeaders(request, email), data: { names: {} } });
  });
}
