import { expect, test } from "@playwright/test";

import { chooseColumn, resetColumns } from "../../columnChooser";
import { installCleanupHook } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a person scanning a list with many columns shows the ones their work needs. A rarely needed column
 * (the Diagrams Switches count) starts hidden, a choice is remembered with the person and survives a reload, and the
 * choice changes the screen only (Sort by still offers the column). The Requirements list, a table shared with other
 * lists, offers the same chooser and keeps its selection and ordering controls.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture switched on; records are created through the API.
 */
test.describe("Column choice on lists", () => {
  test("Diagrams: Switches starts hidden, is chosen, kept across a reload and reset; Sort by keeps offering it", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ColumnsDiagrams", false, "System Architecture");
    const created = await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/architecture/diagrams`, {
      headers: adminHeaders, data: { name: `Overview ${suffix}`, activate: true, populate: true },
    });
    expect(created.ok(), await created.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/modules/architecture/diagrams`);
    const table = page.getByRole("table", { name: "Diagrams" });
    await expect(table.getByText(`Overview ${suffix}`)).toBeVisible();
    for (const header of ["Code", "Name", "Folder", "Contents", "Status"]) await expect(table.getByRole("columnheader", { name: header })).toBeVisible();
    await expect(table.getByRole("columnheader", { name: "Switches" })).toHaveCount(0);
    await expect(page.getByLabel("Sort by").locator("option", { hasText: "Switches" })).toHaveCount(1);

    const saved = page.waitForResponse((r) => r.url().includes("/auth/me") && r.request().method() === "PATCH");
    await chooseColumn(page, "Switches");
    await saved;
    await expect(table.getByRole("columnheader", { name: "Switches" })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("table", { name: "Diagrams" }).getByRole("columnheader", { name: "Switches" })).toBeVisible();

    await resetColumns(page);
    await expect(page.getByRole("table", { name: "Diagrams" }).getByRole("columnheader", { name: "Switches" })).toHaveCount(0);
  });

  test("Requirements: an optional column is hidden and restored, and the selection and order controls stay", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ColumnsReqs");
    const component = await (await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/components`, {
      headers: adminHeaders, data: { name: "Software", prefix: "SW" },
    })).json();
    const category = await (await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/categories`, {
      headers: adminHeaders, data: { name: "Performance", prefix: "PERF", component_id: component.id },
    })).json();
    const name = `Boot within 30 seconds ${suffix}`;
    expect((await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/requirements`, {
      headers: adminHeaders, data: { name, component_id: component.id, category_id: category.id },
    })).ok()).toBeTruthy();

    await page.goto(`/projects/${project.id}/requirements`);
    await page.getByRole("button", { name: "List view" }).click();
    const table = page.getByRole("table", { name: "Requirements" });
    await expect(table.getByText(name)).toBeVisible();
    for (const header of ["ID", "Name", "Status", "Target · level", "Component · category"]) await expect(table.getByRole("columnheader", { name: header })).toBeVisible();
    await expect(table.getByRole("checkbox", { name: /^Select all/ })).toBeVisible();
    await expect(table.getByRole("button", { name: "Move up" }).or(table.getByRole("button", { name: "Up" })).first()).toBeVisible();

    await chooseColumn(page, "Component and category", false);
    await expect(table.getByRole("columnheader", { name: "Component · category" })).toHaveCount(0);
    await expect(table.getByRole("columnheader", { name: "Name" })).toBeVisible();
    await resetColumns(page);
    await expect(table.getByRole("columnheader", { name: "Component · category" })).toBeVisible();

    // Every column sorts across the whole list, including those that need data from other tables.
    for (const header of ["Target · level", "Component · category"]) {
      const sorted = page.waitForResponse((r) => r.url().includes("/requirements?") && r.url().includes("order=asc") && r.ok());
      await table.getByRole("button", { name: header }).click();
      await sorted;
      await expect(table.getByRole("columnheader", { name: header })).toHaveAttribute("aria-sort", "ascending");
    }
  });
});
