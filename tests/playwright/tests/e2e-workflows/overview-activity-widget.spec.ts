import { expect, test } from "@playwright/test";

import { createDisposableProject, installCleanupHook, loginAs, PERSONAS } from "./helpers";

installCleanupHook();

/**
 * Job to be done: read the latest changes on the project overview exactly as the project History page words them.
 *
 * Covers: the overview's activity widget draws the History page's table (Time, Type, Event, Record(s), Person), its
 * first row reads the same as the History page's first row, it stacks its rows when its card is narrow, and
 * "View all history" opens the History page.
 */
test.describe("overview activity widget", () => {
  test("shows the History page's first row and links to the History page", async ({ page }) => {
    const { projectId } = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E Overview Activity");
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    await page.goto(`/projects/${projectId}`);
    const widget = page.getByRole("table", { name: "Project activity" });
    await expect(widget).toBeVisible();
    for (const heading of ["Time", "Type", "Event", "Record", "Person"]) {
      await expect(widget.getByRole("columnheader", { name: new RegExp(`^${heading}`) })).toBeVisible();
    }
    const widgetRow = await widget.locator("tbody tr").first().locator("td").allInnerTexts();

    await page.getByRole("link", { name: "View all history" }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/history`));
    const history = page.getByRole("table", { name: "Project history" });
    await expect(history).toBeVisible();
    const historyRow = await history.locator("tbody tr").first().locator("td").allInnerTexts();

    expect(widgetRow).toEqual(historyRow);
  });

  test("stacks a row when the window is narrow", async ({ page }) => {
    const { projectId } = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E Overview Activity Narrow");
    await page.setViewportSize({ width: 420, height: 900 });
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    await page.goto(`/projects/${projectId}`);
    const widget = page.getByRole("table", { name: "Project activity" });
    await expect(widget).toBeVisible();
    await expect(widget.locator("thead")).toBeHidden();
    const cells = widget.locator("tbody tr").first().locator("td");
    const event = await cells.nth(2).boundingBox();
    const type = await cells.nth(1).boundingBox();
    expect(event!.y).toBeGreaterThanOrEqual(type!.y + type!.height - 1);
  });
});
