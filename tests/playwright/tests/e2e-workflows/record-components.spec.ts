import { expect, test } from "@playwright/test";

import { chooseRecordAddition, createDisposableProject, installCleanupHook, loginAs, PERSONAS, RECORD_ADD_NAME } from "./helpers";

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
      await chooseRecordAddition(page, "Add component or category");
      await page.getByRole("dialog", { name: "Add component or category" }).getByRole("button", { name: "Components and categories" }).click();
      // The chip shows before the change is saved, so wait for the save before the reload reads it back.
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/placements") && r.request().method() === "PUT" && r.ok()),
        page.getByRole("checkbox", { name: "Software / Performance" }).check(),
      ]);
      await page.keyboard.press("Escape");
      await page.keyboard.press("Escape");
      const places = header.getByRole("group", { name: "Tags, components and references" });
      await expect(places).toContainText("Software / Performance");
      await page.reload();
      await expect(page.locator(".record-header").getByRole("group", { name: "Tags, components and references" })).toContainText("Software / Performance");
      // The chip leaves the page before the change is saved, so wait for the save: the API is read in the next step.
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/placements") && r.request().method() !== "GET"),
        page.locator(".record-header").getByRole("button", { name: "Remove Software / Performance" }).click(),
      ]);
      await expect(page.locator(".record-header").getByRole("group", { name: "Tags, components and references" })).not.toContainText("Software / Performance");
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
    // The record header's (+) menu offers no place row: the requirement's own place is its component, and its further
    // places are the category-only picker of its Components card, below the header.
    const plus = page.getByRole("button", { name: RECORD_ADD_NAME });
    await expect(plus).toHaveAccessibleName(/^Add tag( or external reference)?$/);
    await plus.click();
    await expect(page.getByRole("menuitem", { name: "Add tag" })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Add component or category" })).toHaveCount(0);
    await page.keyboard.press("Escape");
    const refused = await page.request.put(`${API}/projects/${projectId}/artefacts/requirement/${requirement.id}/placements`, {
      headers, data: { placements: [] },
    });
    expect(refused.status()).toBe(422);
  });
});
