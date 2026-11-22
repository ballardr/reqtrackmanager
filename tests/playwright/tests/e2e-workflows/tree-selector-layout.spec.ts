import { expect, test } from "@playwright/test";

import { createDisposableProject, installCleanupHook, loginAs, PERSONAS } from "./helpers";

// Archives this file's disposable projects after each test (see createDisposableProject).
installCleanupHook();

/**
 * Job to be done: choose places from the tree selector with a plain expand chevron beside each label and every
 * checkbox in one column at the right edge, whatever the depth (docs/ux-style-guide.md, "Choosing from a tree").
 *
 * Covers (on the Components and categories selector of a new action): the chevron is not drawn as a button, the
 * checkboxes of a component and of its category share one right edge, the chevron works from the keyboard, and
 * pressing a row's label chooses it.
 */
test("the tree selector has a plain chevron and one checkbox column", async ({ page }) => {
  const { projectId } = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E Tree Selector");
  await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
  await page.goto(`/projects/${projectId}/actions`);
  await page.getByRole("button", { name: "New action" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Components and categories" }).click();

  await test.step("the chevron is plain and large enough to touch", async () => {
    const chevron = page.getByRole("button", { name: "Collapse Hardware", exact: true });
    await expect(chevron).toBeVisible();
    await expect(chevron).toHaveCSS("border-top-style", "none");
    await expect(chevron).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
    const box = await chevron.boundingBox();
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(24);
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(24);
  });

  await test.step("a component and its category share one checkbox column, right of the label", async () => {
    const parent = await page.getByRole("checkbox", { name: "Hardware", exact: true }).boundingBox();
    const child = await page.getByRole("checkbox", { name: "Hardware / Functional", exact: true }).boundingBox();
    const label = await page.getByText("Functional", { exact: true }).first().boundingBox();
    expect(parent && child && label).toBeTruthy();
    expect(Math.abs((parent?.x ?? 0) - (child?.x ?? 99))).toBeLessThan(1);
    expect(child?.x ?? 0).toBeGreaterThan((label?.x ?? 0) + (label?.width ?? 0));
  });

  await test.step("the chevron collapses and expands from the keyboard", async () => {
    const chevron = page.getByRole("button", { name: "Collapse Hardware", exact: true });
    await chevron.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("checkbox", { name: "Hardware / Functional", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Expand Hardware", exact: true }).press("Enter");
    await expect(page.getByRole("checkbox", { name: "Hardware / Functional", exact: true })).toBeVisible();
  });

  await test.step("pressing the label chooses the row", async () => {
    await page.getByText("Functional", { exact: true }).first().click();
    await expect(page.getByRole("checkbox", { name: "Hardware / Functional", exact: true })).toBeChecked();
    await expect(page.getByRole("checkbox", { name: "Hardware", exact: true })).not.toBeChecked();
  });
});
