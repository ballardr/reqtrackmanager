import { expect, test } from "@playwright/test";

import { installCleanupHook, loginAs, openProject, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: a person scanning a project's Files list cannot tell what a small thumbnail shows, so a click on it
 * opens a larger preview with a Download link, and a document, which has no picture, offers no preview.
 *
 * Reads the seeded Alpha-1 files "e2e-library-picture.png" and "e2e-direct-attachment.txt" only; nothing is created,
 * so it passes alone, in any order and repeated.
 */
test.describe("project files: a picture's thumbnail opens a larger preview", () => {
  installCleanupHook();

  test("click opens the preview, Escape and the close control close it, and a document has no preview", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openProject(page, PROJECT_NAMES.alpha1);
    await page.getByRole("link", { name: "Files", exact: true }).and(page.locator('[href*="/projects/"]')).click();

    const thumbnail = page.getByRole("button", { name: "Preview e2e-library-picture.png" });
    await expect(thumbnail).toBeVisible();
    await expect(page.getByRole("button", { name: /^Preview e2e-direct-attachment/ })).toHaveCount(0);

    await thumbnail.click();
    const dialog = page.getByRole("dialog", { name: "e2e-library-picture.png" });
    await expect(dialog).toBeVisible();
    const picture = dialog.getByRole("img", { name: "e2e-library-picture.png" });
    await expect(picture).toBeVisible();
    await expect.poll(() => picture.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
    await expect(dialog.getByRole("link", { name: "Download" })).toHaveAttribute("download", "e2e-library-picture.png");

    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(thumbnail).toBeFocused();

    await thumbnail.click();
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: /close/i }).click();
    await expect(dialog).toHaveCount(0);
    await expect(thumbnail).toBeFocused();
  });
});
