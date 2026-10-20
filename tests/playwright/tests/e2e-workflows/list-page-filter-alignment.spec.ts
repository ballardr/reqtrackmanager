import { expect, test } from "@playwright/test";

import { createDisposableProject, installCleanupHook, loginAs, PERSONAS } from "./helpers";

// Archives each disposable project after the test.
installCleanupHook();

/**
 * Job to be done: on every list page with a side filter panel, the panel's top edge is level with the page
 * title, whatever the page puts above its list (a settings row, tabs, a banner), and the list sits to the
 * left of it. One shared layout (`ListPageLayout`) does this, so the check covers three different pages.
 *
 * Builds its own project through the API, so it depends on no shared fixture.
 */
test("the filter panel's top edge is level with the page title on the main list pages", async ({ page, request }) => {
  const project = await createDisposableProject(request, PERSONAS.orgAdminAlphaBeta.email, "E2E Filter Alignment");
  await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

  for (const path of ["requirements", "actions", "change-requests"]) {
    await test.step(`${path}: the filter starts at the title`, async () => {
      await page.goto(`/projects/${project.projectId}/${path}`);
      const title = page.getByRole("heading", { level: 1 }).first();
      const panel = page.locator(".filter-panel").first();
      await expect(panel).toBeVisible();
      const [t, p] = await Promise.all([title.boundingBox(), panel.boundingBox()]);
      expect(Math.abs(t!.y - p!.y)).toBeLessThanOrEqual(3);
      // The title and the list are to the left of the panel, never above or below it.
      expect(t!.x + t!.width).toBeLessThanOrEqual(p!.x + 1);
    });
  }
});
