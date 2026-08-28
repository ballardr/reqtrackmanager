import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS, selectProjectAdminGroup } from "./helpers";

/**
 * RichTextEditor's link-insert toolbar button used to open the browser's
 * native window.prompt() — the one native-prompt usage in the app,
 * inconsistent with every other user-input surface, which goes through the
 * shared Modal component. Fixed to use that same Modal. This proves it in
 * a real page (Project Admin's report intro editor), not just in
 * isolation via Storybook (see RichTextEditor.stories.tsx's own
 * InsertLink story for the component-level coverage) — critically, that no
 * native dialog appears at all, since a native prompt left in place would
 * otherwise silently stall this test (Playwright doesn't auto-handle
 * unexpected dialogs the same way a user would).
 */
test.describe("RichTextEditor: insert-link uses the app's Modal, not window.prompt", () => {
  test("clicking Link opens a dialog with an Insert-link form", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/projects");
    await page.getByRole("link", { name: /Alpha-1/ }).click();
    await page.getByRole("link", { name: "Project admin" }).click();
    await selectProjectAdminGroup(page, "Report Setup");
    await page.getByRole("button", { name: "Rich text" }).first().click();

    await page.getByLabel("Link").first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("Insert link")).toBeVisible();

    const insertButton = dialog.getByRole("button", { name: "Insert" });
    await expect(insertButton).toBeDisabled();
    await dialog.getByLabel("Link URL").fill("https://example.com");
    await expect(insertButton).toBeEnabled();
    await insertButton.click();
    await expect(dialog).not.toBeVisible();
  });
});
