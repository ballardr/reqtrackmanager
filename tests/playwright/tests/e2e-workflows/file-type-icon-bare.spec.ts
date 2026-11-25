import { expect, test } from "@playwright/test";

import { installCleanupHook, loginAs, openProject, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: scanning a long Files list, a person sees a plain file-type icon beside each document, with a filled
 * backdrop only behind a picture, where transparency makes one useful.
 *
 * Reads the seeded attachment "e2e-direct-attachment.txt" on Alpha-1 only; nothing is created, so it passes alone, in
 * any order and repeated.
 */
test.describe("project files: a type icon is drawn bare", () => {
  installCleanupHook();

  test("a document's icon has no background colour or image", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openProject(page, PROJECT_NAMES.alpha1);
    await page.getByRole("link", { name: "Files", exact: true }).and(page.locator('[href*="/projects/"]')).click();

    const row = page.locator("tr", { has: page.getByRole("link", { name: "e2e-direct-attachment.txt", exact: true }) });
    await expect(row).toBeVisible();
    const icon = row.locator(".file-thumb--icon");
    await expect(icon).toHaveCount(1);
    await expect(icon).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
    await expect(icon).toHaveCSS("background-image", "none");
    const box = await icon.boundingBox();
    expect(box?.width).toBeGreaterThan(30);
    expect(box?.width).toBeCloseTo(box?.height ?? 0, 0);
  });
});
