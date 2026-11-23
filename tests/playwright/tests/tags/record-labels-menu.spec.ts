import { expect, test } from "@playwright/test";

import { chooseRecordAddition, installCleanupHook, loginAs, logout, PASSWORD } from "../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "../modules/stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: label a record (a tag, a component, an external reference) from one place in its header, without
 * having to know which of three small controls does which.
 *
 * Covers (on a persona, a module record, so no per-type code is involved): one (+) after the chips whose menu names each
 * addition, all three kinds ending up in one row, the choice surviving a reload, a menu that offers only what the
 * person may do, and a reader who sees the chips with no (+).
 *
 * Disposable organisation, project, component tree and users created through the API, removed afterwards.
 */
test("one (+) in the record header adds a tag, a component and an external reference into one row", async ({ page }) => {
  test.setTimeout(150_000);
  const { suffix, org, project, adminHeaders } = await setUpOrg(page, "LabelsMenu");
  const api = `${API_BASE_URL}/api/v1`;
  const post = async (path: string, data: unknown) => {
    const resp = await page.request.post(`${api}${path}`, { headers: adminHeaders, data });
    expect(resp.ok(), await resp.text()).toBeTruthy();
    const body = await resp.text();
    return body ? JSON.parse(body) : null;
  };
  const component = await post(`/projects/${project.id}/components`, { name: `Platform ${suffix}`, prefix: "PLT" });
  const persona = await post(`/projects/${project.id}/modules/stakeholders/personas`, { name: `Labelled persona ${suffix}` });
  const readerEmail = `e2e-labels-reader-${suffix}@example.com`;
  const reader = await post(`/orgs/${org.id}/users`, {
    email: readerEmail, display_name: `Labels Reader ${suffix}`, password: PASSWORD, role: "member",
  });
  await post(`/projects/${project.id}/roles`, { user_id: reader.user_id, role: "stakeholder" });
  const tag = `Pilot ${suffix}`;
  const key = `PROJ-${suffix}`;
  const group = page.locator("header.record-header").getByRole("group", { name: "Tags, components and references" });
  const addButton = page.getByRole("button", { name: "Add tag, component or reference" });

  await page.goto(`/projects/${project.id}/modules/stakeholders/personas/${persona.id}`);

  await test.step("there is one add control, and its menu names each addition", async () => {
    await expect(addButton).toHaveCount(1);
    await expect(page.getByRole("button", { name: /^Add (tag|external reference)$/ })).toHaveCount(0);
    await addButton.click();
    const menu = page.getByRole("menu", { name: "Add tag, component or reference" });
    await expect(menu.getByRole("menuitem")).toHaveText(["Add tag", "Add component or category", "Add external reference"]);
    await page.keyboard.press("Escape");
    await expect(menu).toHaveCount(0);
  });

  await test.step("a tag, a component and an external reference are added from it", async () => {
    await chooseRecordAddition(page, "Add tag");
    await page.getByRole("combobox", { name: "Tags" }).fill(tag);
    const tagSaved = page.waitForResponse((r) => r.url().includes("/tags") && r.request().method() === "PUT" && r.ok());
    await page.getByRole("option", { name: `Add tag "${tag}"` }).click();
    await tagSaved;
    await page.keyboard.press("Escape");

    await chooseRecordAddition(page, "Add component or category");
    const dialog = page.getByRole("dialog", { name: "Add component or category" });
    await dialog.getByRole("button", { name: "Components and categories" }).click();
    const placed = page.waitForResponse((r) => r.url().includes("/placements") && r.request().method() === "PUT" && r.ok());
    await page.getByRole("checkbox", { name: `Platform ${suffix}`, exact: true }).click();
    await placed;
    await page.keyboard.press("Escape");
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);

    await chooseRecordAddition(page, "Add external reference");
    const form = page.getByRole("dialog", { name: "Add an external reference" });
    await form.getByRole("combobox", { name: "System" }).selectOption({ label: "Jira" });
    await form.getByRole("textbox", { name: "Key" }).fill(key);
    await form.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText("Reference added.")).toBeVisible();
  });

  await test.step("the three chips share one row, in the order tags, components, references, with the (+) last", async () => {
    await expect(group.getByText(tag, { exact: true })).toBeVisible();
    await expect(group.getByText(`Platform ${suffix}`, { exact: true })).toBeVisible();
    await expect(group.getByText(new RegExp(`Jira:\\s*${key}`))).toBeVisible();
    const boxes = await Promise.all([
      group.getByText(tag, { exact: true }),
      group.getByText(`Platform ${suffix}`, { exact: true }),
      group.getByText(new RegExp(`Jira:\\s*${key}`)),
      addButton,
    ].map(async (locator) => (await locator.boundingBox())!));
    // In reading order: each chip is on a later line than the one before, or to its right on the same line (a long chip
    // may wrap the row, and the (+) follows the last chip wherever it ends).
    for (let i = 1; i < boxes.length; i += 1) {
      const before = boxes[i - 1];
      const after = boxes[i];
      const sameLine = Math.abs((after.y + after.height / 2) - (before.y + before.height / 2)) < before.height / 2;
      expect(sameLine ? after.x > before.x : after.y > before.y).toBeTruthy();
    }
  });

  await test.step("the labels survive a reload", async () => {
    await page.reload();
    await expect(group.getByText(tag, { exact: true })).toBeVisible();
    await expect(group.getByText(`Platform ${suffix}`, { exact: true })).toBeVisible();
    await expect(group.getByText(new RegExp(`Jira:\\s*${key}`))).toBeVisible();
  });

  await test.step("a reader sees the chips and has no (+)", async () => {
    await logout(page);
    await loginAs(page, readerEmail, PASSWORD);
    await page.goto(`/projects/${project.id}/modules/stakeholders/personas/${persona.id}`);
    await expect(group.getByText(tag, { exact: true })).toBeVisible();
    await expect(group.getByText(new RegExp(`Jira:\\s*${key}`))).toBeVisible();
    await expect(addButton).toHaveCount(0);
    await expect(group.getByRole("button")).toHaveCount(0);
  });
});
