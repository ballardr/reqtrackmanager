import { expect, test } from "@playwright/test";

import { createDisposableProject, installCleanupHook, loginAs, PERSONAS } from "./helpers";

/**
 * Job to be done: choose a requirement's component and category without a tooltip covering the list.
 *
 * Hovers a chevron, a component heading (a disabled row), a selectable row, the search box and the trigger of the open
 * picker and expects no tooltip bubble and no native `title` anywhere in the picker or its trigger. Uses its own disposable project, so it mutates nothing shared and passes
 * alone, first, last or repeated.
 */
test.describe("tree selector: no stray tooltip", () => {
  installCleanupHook();

  test("an open Component and category picker shows no tooltip", async ({ page }) => {
    const project = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E Tree Tooltip");
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/projects/${project.projectId}/requirements`);
    await page.getByRole("button", { name: "New requirement" }).click();
    const dialog = page.getByRole("dialog", { name: "New requirement" });
    const trigger = dialog.getByRole("button", { name: "Component and category", exact: true });
    await trigger.click();
    const panel = page.getByRole("dialog", { name: "Component and category" });
    const chevron = panel.getByRole("button", { name: /^(Collapse|Expand) / }).first();
    await expect(chevron).toBeVisible();

    const targets = [
      chevron, panel.locator("[role=radio][disabled]").first(), panel.locator("[role=radio]:not([disabled])").first(),
      panel.getByRole("searchbox"), trigger,
    ];
    for (const target of targets) {
      await target.hover();
      // Give a tooltip time to show, were there one.
      await page.waitForTimeout(400);
      await expect(page.getByRole("tooltip")).toHaveCount(0);
    }
    await expect(panel.locator("[title]")).toHaveCount(0);
    await expect(trigger).not.toHaveAttribute("title");
  });
});
