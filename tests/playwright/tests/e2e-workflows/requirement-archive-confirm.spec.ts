import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS } from "./helpers";

/**
 * Archiving a requirement used to fire immediately with no confirmation at
 * all — the one archive button in the app that didn't match its structural
 * sibling on ActionDetailPage, which already used window.confirm. Fixed by
 * adding the same confirmation here. This proves both halves: cancelling
 * the dialog leaves the requirement untouched, accepting it archives and
 * navigates back to the list.
 *
 * Creates its own throwaway requirement rather than reusing seeded data,
 * since archiving isn't reversible from the UI and other specs may depend
 * on the seeded requirements still being present/active.
 */
test.describe("requirement archive: confirmation dialog", () => {
  test("cancel leaves it active; confirm archives and returns to the list", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/projects");
    await page.getByRole("link", { name: /Alpha-1/ }).click();
    await page.getByRole("link", { name: "Requirements", exact: true }).click();

    const name = `E2E Archive Confirm ${Date.now()}`;
    await page.getByRole("button", { name: "New requirement" }).click();
    await page.getByPlaceholder("Name", { exact: true }).fill(name);
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await page.getByText(name).click();

    await test.step("cancelling the dialog leaves the requirement in place", async () => {
      page.once("dialog", (dialog) => dialog.dismiss());
      await page.getByRole("button", { name: "Archive", exact: true }).click();
      await expect(page.getByRole("heading", { name })).toBeVisible();
    });

    await test.step("confirming archives it and returns to the requirements list", async () => {
      let dialogMessage = "";
      page.once("dialog", (dialog) => {
        dialogMessage = dialog.message();
        void dialog.accept();
      });
      await page.getByRole("button", { name: "Archive", exact: true }).click();
      await page.waitForURL(/\/requirements$/);
      expect(dialogMessage).toContain("Archive this requirement?");
      await expect(page.getByText(name)).not.toBeVisible();
    });
  });
});
