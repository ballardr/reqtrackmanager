import { expect, test } from "@playwright/test";

import { createDisposableProject, installCleanupHook, loginAs, PERSONAS } from "./helpers";

/**
 * Job to be done: put a record I have just created or changed at the top of a list. Every record list has a Sort by
 * and an Order field in its filter panel (Code, Title, Created, Modified and the table's own columns), the column
 * headers and the fields are one state, the choice is kept in the address, and the list's Export follows it.
 *
 * Works in its own disposable project so the spec never depends on or alters seeded data.
 */
test.describe("record lists: sort by code, title, created and modified", () => {
  installCleanupHook();
  const API = "http://localhost:8000/api/v1";

  test("the requirements list sorts by created and code, keeps the choice in the address and returns to the default", async ({ page }) => {
    const project = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E List Sort");
    const { headers, projectId } = project;
    const [component] = project.components;
    const [category] = project.categories;
    const stamp = Date.now();
    const names = [`Sort Charlie ${stamp}`, `Sort Alpha ${stamp}`, `Sort Bravo ${stamp}`];
    for (const name of names) {
      const made = await page.request.post(`${API}/projects/${projectId}/requirements`, {
        headers, data: { name, component_id: component.id, category_id: category.id },
      });
      expect(made.ok(), await made.text()).toBeTruthy();
    }

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/projects/${projectId}/requirements`);
    // The column headers and rows are the list view's; the filter panel's fields are the same in either view.
    await page.getByRole("button", { name: "List view" }).click();
    const rows = page.getByRole("row");
    const sortBy = page.getByRole("combobox", { name: "Sort by" });
    const order = page.getByRole("combobox", { name: "Order" });

    await test.step("the default is the component and category order, with no direction", async () => {
      await expect(page.getByText(names[0])).toBeVisible();
      await expect(sortBy).toHaveValue("component");
      await expect(order).toBeDisabled();
    });

    await test.step("Created, newest first, puts the record created last at the top", async () => {
      await sortBy.selectOption("created");
      await order.selectOption("desc");
      await expect(rows.nth(1)).toContainText(names[2]);
      await expect(rows.nth(3)).toContainText(names[0]);
      await expect(page).toHaveURL(/sort=created/);
      await expect(page).toHaveURL(/order=desc/);
    });

    await test.step("a column header and the Sort by field are one state", async () => {
      await page.getByRole("button", { name: "Name", exact: true }).click();
      await expect(sortBy).toHaveValue("name");
      await expect(order).toHaveValue("asc");
      await expect(rows.nth(1)).toContainText(names[1]);
    });

    await test.step("the last choice is remembered when the list is opened again with no sort in the address", async () => {
      await expect(async () => {
        await page.goto(`/projects/${projectId}/requirements`);
        await expect(sortBy).toHaveValue("name", { timeout: 2000 });
      }).toPass();
      await expect(page).not.toHaveURL(/sort=/);
      await page.getByRole("button", { name: "List view" }).click();
      await expect(rows.nth(1)).toContainText(names[1]);
    });

    await test.step("the choice survives a reload, and choosing Component and category returns to the default", async () => {
      await page.reload();
      await expect(sortBy).toHaveValue("name");
      await expect(rows.nth(1)).toContainText(names[1]);
      await sortBy.selectOption("component");
      await expect(sortBy).toHaveValue("component");
      await expect(order).toBeDisabled();
    });

    await test.step("Code descending orders by the code, and the Export follows the sort", async () => {
      await sortBy.selectOption("unique_code");
      await order.selectOption("desc");
      await expect(rows.nth(1)).toContainText(names[2]);
      const exported = await page.request.get(
        `${API}/projects/${projectId}/records/requirement/export?sort=code&order=desc`, { headers },
      );
      expect(exported.ok()).toBeTruthy();
      const lines = (await exported.text()).trim().split("\n");
      const codes = lines.slice(1).map((line) => line.split(",")[0].replace(/"/g, ""));
      expect(codes).toEqual([...codes].sort((a, b) => b.localeCompare(a, undefined, { numeric: true })));
    });
  });

  test("the actions list sorts by title and offers Modified", async ({ page }) => {
    const project = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E Action Sort");
    const { headers, projectId } = project;
    const types: { id: string }[] = await (await page.request.get(`${API}/projects/${projectId}/action-types`, { headers })).json();
    const stamp = Date.now();
    const titles = [`Zulu ${stamp}`, `Alpha ${stamp}`, `Mike ${stamp}`];
    for (const title of titles) {
      const made = await page.request.post(`${API}/projects/${projectId}/actions`, { headers, data: { title, action_type_id: types[0].id } });
      expect(made.ok(), await made.text()).toBeTruthy();
    }

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/projects/${projectId}/actions`);
    await expect(page.getByText(titles[0])).toBeVisible();
    const sortBy = page.getByRole("combobox", { name: "Sort by" });
    await expect(sortBy.getByRole("option", { name: "Modified" })).toHaveCount(1);
    await sortBy.selectOption("title");
    const rows = page.getByRole("row");
    await expect(rows.nth(1)).toContainText(titles[1]);
    await expect(rows.nth(3)).toContainText(titles[0]);
    await page.getByRole("combobox", { name: "Order" }).selectOption("desc");
    await expect(rows.nth(1)).toContainText(titles[0]);

    await test.step("a created action is confirmed by its code with an Open button, wherever the sort puts it", async () => {
      const created = `Aardvark ${stamp}`;
      await page.getByRole("button", { name: "New action" }).click();
      await page.getByLabel("Title").fill(created);
      await page.getByRole("button", { name: "Create", exact: true }).click();
      const toast = page.getByText(/^Action \S+-\d+ created\.$/);
      await expect(toast).toBeVisible();
      await page.getByRole("button", { name: /^Open \S+-\d+$/ }).click();
      await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/actions/[0-9a-f-]+$`));
      await expect(page.getByText(created).first()).toBeVisible();
    });
  });
});
