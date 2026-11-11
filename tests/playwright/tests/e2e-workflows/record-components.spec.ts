import { expect, test } from "@playwright/test";

import { createDisposableProject, installCleanupHook, loginAs, PERSONAS } from "./helpers";

// Archives this file's disposable projects after each test (see createDisposableProject).
installCleanupHook();

/**
 * Job to be done: place any record in the project's components and categories, and find it again by them, without
 * a per-type screen.
 *
 * Covers (on an Action, a core type with no module needed): choosing components on the create form, adding and
 * removing a place from the record's header, the Components column on the list, the list's component filter, and
 * that a requirement keeps its own component and shows no place picker.
 */
const API = "http://localhost:8000/api/v1";

test.describe("components on every record", () => {
  test("an action is placed on create, changed in its header and found by component", async ({ page }) => {
    const project = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E Components");
    const { projectId, headers, components, categories } = project;
    const suffix = Date.now();
    const actionTypes: { id: string }[] = await (await page.request.get(`${API}/projects/${projectId}/action-types`, { headers })).json();
    const plain = await (
      await page.request.post(`${API}/projects/${projectId}/actions`, {
        headers, data: { title: `E2E Unplaced Action ${suffix}`, action_type_id: actionTypes[0].id },
      })
    ).json();
    expect(plain.id).toBeTruthy();

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    await test.step("create an action in a component and category", async () => {
      await page.goto(`/projects/${projectId}/actions`);
      await page.getByRole("button", { name: "New action" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByRole("textbox", { name: "Title" }).fill(`E2E Placed Action ${suffix}`);
      await dialog.getByRole("button", { name: "Components and categories" }).click();
      await page.getByRole("checkbox", { name: "Hardware / Functional" }).check();
      await page.keyboard.press("Escape");
      await dialog.getByRole("button", { name: "Create" }).click();
      await expect(page.getByRole("dialog")).toHaveCount(0);
    });

    await test.step("the list shows the Components column and filters by component", async () => {
      const row = page.getByRole("row", { name: new RegExp(`E2E Placed Action ${suffix}`) });
      await expect(page.getByRole("columnheader", { name: "Components" })).toBeVisible();
      await expect(row).toContainText("Hardware / Functional");
      await page.getByRole("button", { name: "Component and category", exact: true }).click();
      await page.getByRole("checkbox", { name: "Software", exact: true }).check();
      await expect(page.getByRole("row", { name: new RegExp(`E2E Placed Action ${suffix}`) })).toHaveCount(0);
      await page.getByRole("checkbox", { name: "Software", exact: true }).uncheck();
      await page.getByRole("checkbox", { name: "Hardware", exact: true }).check();
      await expect(page.getByRole("row", { name: new RegExp(`E2E Placed Action ${suffix}`) })).toHaveCount(1);
      await expect(page.getByRole("row", { name: new RegExp(`E2E Unplaced Action ${suffix}`) })).toHaveCount(0);
    });

    await test.step("a place is added and removed from the record's header", async () => {
      await page.goto(`/projects/${projectId}/actions/${plain.id}`);
      const header = page.locator(".record-header");
      await header.getByRole("button", { name: "Components and categories" }).click();
      await page.getByRole("checkbox", { name: "Software / Performance" }).check();
      await page.keyboard.press("Escape");
      const places = header.getByRole("group", { name: "Components" });
      await expect(places).toContainText("Software / Performance");
      await page.reload();
      await expect(page.locator(".record-header").getByRole("group", { name: "Components" })).toContainText("Software / Performance");
      // The chip leaves the page before the change is saved, so wait for the save: the API is read in the next step.
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/placements") && r.request().method() !== "GET"),
        page.locator(".record-header").getByRole("button", { name: "Remove Software / Performance" }).click(),
      ]);
      await expect(page.locator(".record-header").getByRole("group", { name: "Components" })).not.toContainText("Software / Performance");
    });

    await test.step("the places are in the API as component and category ids", async () => {
      const read = await page.request.get(`${API}/projects/${projectId}/artefacts/requirement_action/${plain.id}/placements`, { headers });
      expect((await read.json()).placements).toEqual([]);
      const set = await page.request.put(`${API}/projects/${projectId}/artefacts/requirement_action/${plain.id}/placements`, {
        headers, data: { placements: [{ component_id: components[1].id, category_id: categories[1].id }] },
      });
      expect(set.ok()).toBeTruthy();
    });
  });

  test("a requirement keeps its own component and offers no place picker", async ({ page }) => {
    const project = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E Requirement Component");
    const { projectId, headers, components, categories } = project;
    const requirement = await (
      await page.request.post(`${API}/projects/${projectId}/requirements`, {
        headers, data: { name: `E2E Component Requirement ${Date.now()}`, component_id: components[0].id, category_id: categories[0].id },
      })
    ).json();
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/projects/${projectId}/requirements/${requirement.id}`);
    await expect(page.locator(".record-header")).toBeVisible();
    await expect(page.getByRole("button", { name: "Components and categories" })).toHaveCount(0);
    const refused = await page.request.put(`${API}/projects/${projectId}/artefacts/requirement/${requirement.id}/placements`, {
      headers, data: { placements: [] },
    });
    expect(refused.status()).toBe(422);
  });
});
