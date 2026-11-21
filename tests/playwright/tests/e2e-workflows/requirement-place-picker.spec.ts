import { expect, test } from "@playwright/test";

import { createDisposableProject, installCleanupHook, loginAs, PERSONAS } from "./helpers";

/**
 * Job to be done: choose the one component and category of a new requirement as a single choice from the project's
 * tree, so the pair cannot disagree and its prefixes form the requirement's code.
 *
 * Uses its own disposable project (Hardware / Functional, Software / Performance), so it mutates nothing shared and
 * passes alone, first, last or repeated.
 */
test.describe("requirement create form: component and category as one choice", () => {
  installCleanupHook();

  test("the tree selector chooses a category with its component, and the code takes both prefixes", async ({ page }) => {
    const project = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E Place Picker");
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/projects/${project.projectId}/requirements`);
    await page.getByRole("button", { name: "New requirement" }).click();
    const dialog = page.getByRole("dialog", { name: "New requirement" });
    await dialog.getByPlaceholder("Name", { exact: true }).fill("Chosen from the tree");

    const place = dialog.getByRole("button", { name: "Component and category", exact: true });
    await expect(place).toHaveText(/Hardware \/ Functional/);
    await place.click();
    const choices = page.getByRole("radiogroup", { name: "Component and category" });
    // A component is a heading, not a choice.
    await expect(choices.getByRole("radio", { name: "Software", exact: true })).toBeDisabled();
    await choices.getByRole("radio", { name: "Software / Performance" }).click();
    await expect(place).toHaveText(/Software \/ Performance/);

    await dialog.getByRole("button", { name: "Create", exact: true }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByText(/SW-PERF-\d{3}/).first()).toBeVisible();
  });

  test("a project manager adds the first component and category from the create form with suggested prefixes", async ({ page }) => {
    const project = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E First Structure");
    for (const category of project.categories) {
      const gone = await page.request.delete(`http://localhost:8000/api/v1/projects/${project.projectId}/categories/${category.id}`, { headers: project.headers });
      expect(gone.ok()).toBeTruthy();
    }
    for (const component of project.components) {
      const gone = await page.request.delete(`http://localhost:8000/api/v1/projects/${project.projectId}/components/${component.id}`, { headers: project.headers });
      expect(gone.ok()).toBeTruthy();
    }
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/projects/${project.projectId}/requirements`);
    await page.getByRole("button", { name: "New requirement" }).click();
    const dialog = page.getByRole("dialog", { name: "New requirement" });

    await dialog.getByRole("textbox", { name: "Name" }).fill("Core Platform");
    await expect(dialog.getByRole("textbox", { name: "Prefix" })).toHaveValue("CP");
    await dialog.getByRole("button", { name: "New component" }).click();
    // The form for the first category replaces this one once the component exists.
    await expect(dialog.getByRole("button", { name: "New category" })).toBeVisible();

    await dialog.getByRole("textbox", { name: "Name" }).fill("Boot Sequence");
    await expect(dialog.getByRole("textbox", { name: "Prefix" })).toHaveValue("BS");
    await dialog.getByRole("button", { name: "New category" }).click();

    await expect(dialog.getByRole("button", { name: "Component and category", exact: true })).toHaveText(/Core Platform \/ Boot Sequence/);
    await dialog.getByPlaceholder("Name", { exact: true }).fill("First requirement");
    await dialog.getByRole("button", { name: "Create", exact: true }).click();
    await expect(page.getByText(/CP-BS-\d{3}/).first()).toBeVisible();
  });
});
