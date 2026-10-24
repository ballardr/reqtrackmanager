import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: someone filling in a long Pain Point form (create or edit) can Save or Cancel from the
 * dialog's header at any scroll position, without scrolling to the end of the form, and the header
 * carries the validation state and the save error.
 *
 * Disposable org, created through the API and removed afterwards, so the spec depends on no seeded
 * state and can be repeated against the same database.
 */
test("Save and Cancel stay in the pinned header of the Pain Point create and edit forms", async ({ page }) => {
  const { suffix, org, project, adminHeaders } = await setUpOrg(page, "FormHeader");
  const enable = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/context_strategy`, {
    headers: adminHeaders, data: { enabled: true },
  });
  expect(enable.ok()).toBeTruthy();
  const title = `Header form ${suffix}`;

  await page.setViewportSize({ width: 1100, height: 600 });
  await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points`);
  await page.getByRole("button", { name: "New Pain Point" }).click();
  const dialog = page.getByRole("dialog", { name: "New Pain Point" });
  const save = dialog.getByRole("button", { name: "Save", exact: true });
  const body = dialog.locator(".dialog-body");

  await test.step("the actions sit in the header row beside the title, above the scrolling body", async () => {
    const dialogBox = (await dialog.boundingBox())!;
    const saveBox = (await save.boundingBox())!;
    const bodyBox = (await body.boundingBox())!;
    expect(saveBox.y + saveBox.height).toBeLessThanOrEqual(bodyBox.y + 1);
    expect(saveBox.y - dialogBox.y).toBeLessThan(80);
    await expect(save).toBeDisabled(); // no type or title yet
  });

  await test.step("scrolling the body leaves Save where it was", async () => {
    // The short viewport makes the body overflow, so there is something to scroll.
    expect(await body.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true);
    const before = (await save.boundingBox())!;
    await body.evaluate((el) => { el.scrollTop = el.scrollHeight; });
    const after = (await save.boundingBox())!;
    expect(after.y).toBe(before.y);
    await expect(save).toBeInViewport();
  });

  await dialog.getByLabel("Type", { exact: true }).selectOption({ label: "Operator" });
  await dialog.getByLabel("Pain Point title").fill(title);
  await expect(save).toBeEnabled();

  await test.step("Escape closes the form without saving", async () => {
    await dialog.getByLabel("Pain Point title").press("Escape");
    await expect(dialog).not.toBeVisible();
    await expect(page.getByText(title)).toHaveCount(0);
    await page.getByRole("button", { name: "New Pain Point" }).click();
    await dialog.getByLabel("Type", { exact: true }).selectOption({ label: "Operator" });
    await dialog.getByLabel("Pain Point title").fill(title);
  });

  await test.step("Save from the header, with the body scrolled to the end, creates the record", async () => {
    await body.evaluate((el) => { el.scrollTop = el.scrollHeight; });
    await save.click();
    await expect(dialog).not.toBeVisible();
    await expect(page.getByText(title).first()).toBeVisible();
  });

  await test.step("the edit form has the same header", async () => {
    await page.getByText(title).first().click();
    await page.getByRole("button", { name: "Edit" }).first().click();
    const editDialog = page.getByRole("dialog", { name: `Edit ${title}` });
    const editSave = editDialog.getByRole("button", { name: "Save", exact: true });
    const editBody = editDialog.locator(".dialog-body");
    const saveBox = (await editSave.boundingBox())!;
    const bodyBox = (await editBody.boundingBox())!;
    expect(saveBox.y + saveBox.height).toBeLessThanOrEqual(bodyBox.y + 1);
    await editDialog.getByRole("button", { name: "Cancel" }).click();
    await expect(editDialog).not.toBeVisible();
  });
});
