import { expect, test, type Page } from "@playwright/test";

import { createDisposableProject, installCleanupHook, loginAs, PERSONAS, type DisposableProject } from "./helpers";

// Archives each disposable project after the test.
installCleanupHook();

/**
 * Job to be done: editing down a list. After opening a record and coming back (the browser's Back), the list
 * shows the same rows at the same scroll offset, including rows loaded with "Show more", under the same
 * filters; a fresh visit starts at the top.
 *
 * Builds its own project with 45 requirements (the list loads 30 at a time), so it depends on no shared fixture.
 */
const TOTAL = 45;
const apiBase = "http://localhost:8000/api/v1";

async function projectWithRequirements(request: import("@playwright/test").APIRequestContext): Promise<DisposableProject> {
  const project = await createDisposableProject(request, PERSONAS.orgAdminAlphaBeta.email, "E2E List Position");
  const component = project.components[0];
  const category = project.categories.find((c) => c.component_id === component.id)!;
  for (let n = 1; n <= TOTAL; n++) {
    const resp = await request.post(`${apiBase}/projects/${project.projectId}/requirements`, {
      headers: project.headers,
      data: { name: `Position item ${String(n).padStart(3, "0")}`, component_id: component.id, category_id: category.id },
    });
    expect(resp.ok()).toBeTruthy();
  }
  return project;
}

/** The requirement's row link on the list, found by name. */
function rowLink(page: Page, n: number) {
  return page.getByRole("link", { name: new RegExp(`Position item ${String(n).padStart(3, "0")}`) }).first();
}

async function openList(page: Page, project: DisposableProject) {
  await page.goto(`/projects/${project.projectId}/requirements`);
  await expect(page.getByText("Loading…")).toBeHidden();
  await expect(rowLink(page, 1)).toBeVisible();
}

test("going back from a record returns to the same rows and scroll offset, including rows loaded with Show more", async ({ page, request }) => {
  const project = await projectWithRequirements(request);
  await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
  await openList(page, project);

  await page.getByRole("button", { name: /Load more/ }).click();
  const target = rowLink(page, 40);
  await expect(target).toBeVisible();
  await target.scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollBy(0, 150));
  const before = await page.evaluate(() => window.scrollY);
  expect(before).toBeGreaterThan(300);
  const targetTop = (await target.boundingBox())!.y;

  await target.click();
  await page.waitForURL(/\/requirements\/[0-9a-f-]+(?:[/?#]|$)/);
  await expect(page.locator(".record-header h1")).toBeVisible();

  await page.goBack();
  await expect(target).toBeVisible();
  // The rows loaded with "Show more" are back, and the same row is at the same place on screen.
  await expect(page.getByRole("button", { name: /Load more/ })).toHaveCount(0);
  await expect.poll(async () => Math.abs((await target.boundingBox())!.y - targetTop)).toBeLessThanOrEqual(4);
  expect(Math.abs((await page.evaluate(() => window.scrollY)) - before)).toBeLessThanOrEqual(4);
});

test("going back keeps the filters the list was left with, and a fresh visit starts at the top", async ({ page, request }) => {
  const project = await projectWithRequirements(request);
  await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
  await openList(page, project);

  await page.getByPlaceholder("Search by name or ID").fill("Position item 04");
  await expect(page).toHaveURL(/[?&]q=Position(\+|%20)item(\+|%20)04/);
  await expect(rowLink(page, 41)).toBeVisible();
  await expect(rowLink(page, 3)).toHaveCount(0);

  await rowLink(page, 42).click();
  await page.waitForURL(/\/requirements\/[0-9a-f-]+(?:[/?#]|$)/);
  await page.goBack();

  await expect(page.getByPlaceholder("Search by name or ID")).toHaveValue("Position item 04");
  await expect(rowLink(page, 42)).toBeVisible();
  await expect(rowLink(page, 3)).toHaveCount(0);

  await test.step("opening the list afresh (not by Back) starts at the top, unfiltered", async () => {
    await page.getByRole("link", { name: "Requirements", exact: true }).first().click();
    await expect(page.getByPlaceholder("Search by name or ID")).toHaveValue("");
    expect(await page.evaluate(() => window.scrollY)).toBeLessThanOrEqual(4);
  });
});
