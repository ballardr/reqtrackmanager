import { expect, test } from "@playwright/test";

import { installCleanupHook } from "./e2e-workflows/helpers";
import { chooseMarkdownView, type MarkdownViewName } from "./markdownViews";
import { API_BASE_URL, setUpOrg } from "./modules/stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a form with several Markdown fields (a requirement has three) is not mostly editor chrome. An empty
 * field is the same compact box in Visual, Write and Preview, the Visual, Write and Preview buttons sit on the caption
 * line and are drawn only while the field is in use, and the formatting toolbar takes a row only then.
 *
 * Disposable org, created through the API and removed afterwards, so the spec depends on no seeded state.
 */
test("the new requirement form's Markdown fields are compact, one height in every view, and show their controls only while in use", async ({ page }) => {
  const { project, adminHeaders } = await setUpOrg(page, "MdChrome");
  const base = `${API_BASE_URL}/api/v1/projects/${project.id}`;
  // The form needs a component and a category before it offers its fields.
  const component = await (await page.request.post(`${base}/components`, { headers: adminHeaders, data: { name: "Software", prefix: "SW" } })).json();
  const category = await (await page.request.post(`${base}/categories`, {
    headers: adminHeaders, data: { name: "Performance", prefix: "PERF", component_id: component.id },
  })).json();
  expect(category.id).toBeTruthy();
  await page.goto(`/projects/${project.id}/requirements`);
  await page.getByRole("button", { name: "New requirement" }).click();
  const dialog = page.getByRole("dialog", { name: "New requirement" });
  const fields = dialog.locator(".markdown-editor");
  await expect(fields).toHaveCount(3);

  await test.step("a resting form draws no view buttons and no formatting toolbar", async () => {
    await expect(dialog.getByRole("group", { name: "Editor view" })).toHaveCount(0);
    await expect(dialog.getByRole("toolbar")).toHaveCount(0);
  });

  const heights: number[] = [];
  const height = async (index: number) => Math.round((await fields.nth(index).locator(".md-box").first().boundingBox())?.height ?? 0);

  await test.step("an empty field is one height in Visual, Write and Preview, and all three fields share it", async () => {
    for (let index = 0; index < 3; index += 1) {
      const seen: number[] = [];
      for (const view of ["Visual", "Write", "Preview"] as MarkdownViewName[]) {
        await chooseMarkdownView(fields.nth(index), view);
        if (view === "Visual") await expect(fields.nth(index).locator(".visual-markdown-content")).toBeVisible({ timeout: 30_000 });
        seen.push(await height(index));
      }
      expect(new Set(seen).size, `field ${index}: ${seen.join(", ")}`).toBe(1);
      heights.push(seen[0]);
    }
    expect(new Set(heights).size, heights.join(", ")).toBe(1);
    // Two lines, their padding and border: more than one line and well under the 12rem box this replaced.
    expect(heights[0]).toBeGreaterThan(40);
    expect(heights[0]).toBeLessThan(90);
  });

  await test.step("the view buttons are on the caption line, toolbar size, and using the field changes no caption", async () => {
    const field = fields.nth(0);
    const caption = field.locator(".field-caption");
    await dialog.getByPlaceholder("Name", { exact: true }).click();
    await expect(dialog.getByRole("group", { name: "Editor view" })).toHaveCount(0);
    const before = (await caption.boundingBox())?.height ?? 0;
    await chooseMarkdownView(field, "Write");
    const group = field.getByRole("group", { name: "Editor view" });
    await expect(group).toBeVisible();
    expect(await caption.locator(".view-switch").count()).toBe(1);
    expect((await caption.boundingBox())?.height ?? 0).toBe(before);
    const button = group.getByRole("button", { name: "Preview", exact: true });
    const box = await button.boundingBox();
    expect(Math.round(box?.width ?? 0)).toBe(28);
    expect(Math.round(box?.height ?? 0)).toBe(28);
  });

  await test.step("the formatting toolbar takes its row only while the field is in use", async () => {
    await expect(dialog.getByRole("toolbar", { name: "Formatting" })).toHaveCount(1);
    await dialog.getByPlaceholder("Name", { exact: true }).click();
    await expect(dialog.getByRole("toolbar")).toHaveCount(0);
    await expect(dialog.getByRole("group", { name: "Editor view" })).toHaveCount(0);
  });
});
