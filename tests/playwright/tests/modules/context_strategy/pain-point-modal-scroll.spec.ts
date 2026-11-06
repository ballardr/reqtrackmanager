import { expect, test } from "@playwright/test";

import { closeDialogWithoutSaving, installCleanupHook } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: scrolling inside a dialog (a long Pain Point form) never scrolls the page behind it, even
 * when the scroll reaches the end of the dialog's own body or the pointer is over the backdrop.
 *
 * Disposable org, created through the API and removed afterwards, so the spec can be repeated.
 */
test("scrolling a Pain Point dialog does not scroll the page behind it", async ({ page }) => {
  const { org, project, adminHeaders } = await setUpOrg(page, "ModalScroll");
  const enable = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/context_strategy`, {
    headers: adminHeaders, data: { enabled: true },
  });
  expect(enable.ok()).toBeTruthy();

  await page.setViewportSize({ width: 1100, height: 600 });
  await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points`);
  // Make the page itself scrollable, so a leak would show.
  await page.evaluate(() => { document.body.style.minHeight = "3000px"; });
  await page.getByRole("button", { name: "New Pain Point" }).click();
  const dialog = page.getByRole("dialog", { name: "New Pain Point" });
  const body = dialog.locator(".dialog-body");
  expect(await body.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true);

  await test.step("the page cannot scroll while the dialog is open", async () => {
    expect(await page.evaluate(() => getComputedStyle(document.body).overflow)).toBe("hidden");
    await body.hover();
    await page.mouse.wheel(0, 3000); // past the end of the dialog body
    await page.mouse.wheel(0, 3000);
    await page.mouse.move(5, 300); // over the backdrop
    await page.mouse.wheel(0, 3000);
    expect(await page.evaluate(() => window.scrollY)).toBe(0);
  });

  await test.step("the page scrolls again once the dialog is closed", async () => {
    await closeDialogWithoutSaving(dialog, { unsaved: false });
    await expect(dialog).toHaveCount(0);
    expect(await page.evaluate(() => getComputedStyle(document.body).overflow)).not.toBe("hidden");
  });
});
