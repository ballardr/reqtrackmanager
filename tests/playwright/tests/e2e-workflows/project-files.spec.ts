import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: browsing every file in a project from one place, rather
 * than opening each requirement/action/comment individually — the gap
 * ProjectOverviewPage's "Files" metric tile always counted (only direct
 * requirement attachments, per `ProjectMetricsOut.file_count`'s own
 * narrower scope) but never let you actually see. See
 * backend/scripts/seed_e2e_dataset.py's "Files on Alpha-1" step, which
 * seeds one file via each of the three origins this page combines: a
 * direct requirement attachment (on the requirement named "Must expose a
 * health-check endpoint"), a requirement action attachment (on "E2E
 * Review Action"), and a comment attachment (on "Must support role-based
 * access control").
 */
test.describe("project files", () => {
  test("the Files page lists files from multiple requirements/actions, a download link works, and the dashboard tile links here", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.getByText(PROJECT_NAMES.alpha1).click();
    await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);

    await test.step("the nav rail has a Files link, consistent with the project's other sub-pages (History, Actions, ...)", async () => {
      await expect(page.getByRole("link", { name: "Files", exact: true })).toBeVisible();
    });

    await test.step("the overview's Files tile navigates to the project files page, not the unfiltered requirements list", async () => {
      const filesTile = page.locator(".grid-metrics").getByRole("link", { name: /Files/ });
      await filesTile.click();
      await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+\/files$/);
    });

    await test.step("files from all three origins are listed, each linking back to where it came from", async () => {
      await expect(page.getByRole("cell", { name: "e2e-direct-attachment.txt" })).toBeVisible();
      await expect(page.getByRole("cell", { name: "e2e-action-attachment.pdf" })).toBeVisible();
      await expect(page.getByRole("cell", { name: "e2e-comment-attachment.txt" })).toBeVisible();

      const directRow = page.locator("tr", { has: page.getByText("e2e-direct-attachment.txt") });
      await expect(directRow.getByRole("link", { name: /Must expose a health-check endpoint/ })).toBeVisible();

      const actionRow = page.locator("tr", { has: page.getByText("e2e-action-attachment.pdf") });
      await expect(actionRow.getByRole("link", { name: /E2E Review Action/ })).toBeVisible();

      const commentRow = page.locator("tr", { has: page.getByText("e2e-comment-attachment.txt") });
      await expect(commentRow.getByRole("link", { name: /Must support role-based access control/ })).toBeVisible();
    });

    await test.step("a download link actually serves the file's bytes", async () => {
      const link = page.getByRole("link", { name: "e2e-direct-attachment.txt" });
      const href = await link.getAttribute("href");
      expect(href).toContain("/api/v1/files/");
      const resp = await page.request.get(href!);
      expect(resp.status()).toBe(200);
      expect(await resp.text()).toBe("E2E direct requirement attachment.");
    });

    await test.step("navigating here directly via the nav rail also works", async () => {
      await page.getByRole("link", { name: "Files", exact: true }).click();
      await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+\/files$/);
      await expect(page.getByRole("cell", { name: "e2e-direct-attachment.txt" })).toBeVisible();
    });
  });
});
