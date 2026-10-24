import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a Pain Point author who pastes a long description sees all of it as far as the
 * field's height cap allows, instead of scrolling inside a two-row box, in the create form and in the
 * edit form opened from the detail page.
 *
 * Disposable org, created through the API and removed afterwards, so the spec depends on no seeded
 * state and can be repeated against the same database.
 */
test("the Pain Point description grows with long text in the create and edit forms", async ({ page }) => {
  const { suffix, org, project, adminHeaders } = await setUpOrg(page, "TextGrows");
  const enable = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/context_strategy`, {
    headers: adminHeaders, data: { enabled: true },
  });
  expect(enable.ok()).toBeTruthy();
  const title = `Long description ${suffix}`;
  const longText = Array.from({ length: 40 }, (_, i) => `Line ${i + 1}`).join("\n");

  await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points`);
  await page.getByRole("button", { name: "New Pain Point" }).click();
  const dialog = page.getByRole("dialog", { name: "New Pain Point" });
  await dialog.getByLabel("Type", { exact: true }).selectOption({ label: "Operator" });
  await dialog.getByLabel("Pain Point title").fill(title);

  const description = dialog.getByLabel("Description", { exact: true });
  const height = async () => (await description.boundingBox())!.height;

  await test.step("create form: pasting 40 lines grows the box up to its cap", async () => {
    const emptyHeight = await height();
    await description.fill(longText);
    const grownHeight = await height();
    expect(grownHeight).toBeGreaterThan(emptyHeight * 2);
    // Capped (about 8 lines), so a pasted essay does not push Save and the other fields away.
    expect(await description.evaluate((el) => el.scrollHeight)).toBeGreaterThan(grownHeight);
    expect(grownHeight).toBeLessThan(400);
  });

  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog).not.toBeVisible();

  await test.step("edit form: the saved long text opens already grown", async () => {
    await page.getByText(title).first().click();
    await page.getByRole("button", { name: "Edit" }).first().click();
    const editDialog = page.getByRole("dialog", { name: `Edit ${title}` });
    const editDescription = editDialog.getByLabel("Description", { exact: true });
    await expect(editDescription).toHaveValue(longText);
    expect((await editDescription.boundingBox())!.height).toBeGreaterThan(100);
  });
});
