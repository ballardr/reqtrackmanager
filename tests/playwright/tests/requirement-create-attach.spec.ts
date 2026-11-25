import { expect, test } from "@playwright/test";

import { addStructureCategory, addStructureComponent, structureRow, selectProjectAdminGroup } from "./e2e-workflows/helpers";

/**
 * The create modal's "Create" button closes the modal at once; a separate "Create & attach files" action
 * advances the same modal to a second step against the just-created requirement's id before closing. Links are
 * chosen in the create form's "Link to" field. The action is opt-in because most creates do not need it and
 * every other workflow (the golden path included) depends on a plain "Create" staying a single, modal-closing
 * action.
 */
test("Create & attach files advances to an attach-files step, then finishes", async ({ page }) => {
  const ADMIN_EMAIL = "admin@example.com";
  const ADMIN_PASSWORD = "ChangeMe123!";
  const projectName = `Attach Flow ${Date.now()}`;

  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/projects(\/|$)/);

  await page.goto("/projects");
  await page.getByRole("button", { name: "New project" }).click();
  const newProjectDialog = page.getByRole("dialog", { name: "New project" });
  await newProjectDialog.getByLabel("Name", { exact: true }).fill(projectName);
  await newProjectDialog.getByRole("button", { name: "Create" }).click();
  await page.waitForURL(/\/projects\/[^/]+$/);

  // Set up a component/category first via Project Admin, matching
  // golden-path.spec.ts's own established pattern — a fresh project has
  // neither yet.
  await page.getByText("Project Admin").click();
  await selectProjectAdminGroup(page, "Structure");
  await addStructureComponent(page, "Software", "SW");
  await addStructureCategory(page, "Software", "Performance", "PERF");
  await expect(structureRow(page, "Performance")).toBeVisible();

  await page.getByRole("link", { name: "Requirements", exact: true }).click();
  await page.getByRole("button", { name: "New requirement" }).click();
  const createDialog = page.getByRole("dialog", { name: "New requirement" });
  await createDialog.getByPlaceholder("Name", { exact: true }).fill("Password reset");
  await createDialog.getByRole("button", { name: "Create & attach files" }).click();

  const step2 = page.getByRole("dialog", { name: /Attach files/ });
  await expect(step2).toBeVisible();
  await expect(step2.getByText("Attachments")).toBeVisible();

  await step2.getByRole("button", { name: "Finish" }).click();
  await expect(page.getByRole("dialog", { name: /Attach files/ })).not.toBeVisible();
  await expect(page.getByText("Password reset")).toBeVisible();
});

test("plain Create closes the modal immediately, unchanged", async ({ page }) => {
  const ADMIN_EMAIL = "admin@example.com";
  const ADMIN_PASSWORD = "ChangeMe123!";
  const projectName = `Plain Create ${Date.now()}`;

  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/projects(\/|$)/);

  await page.goto("/projects");
  await page.getByRole("button", { name: "New project" }).click();
  const newProjectDialog = page.getByRole("dialog", { name: "New project" });
  await newProjectDialog.getByLabel("Name", { exact: true }).fill(projectName);
  await newProjectDialog.getByRole("button", { name: "Create" }).click();
  await page.waitForURL(/\/projects\/[^/]+$/);

  await page.getByText("Project Admin").click();
  await selectProjectAdminGroup(page, "Structure");
  await addStructureComponent(page, "Software", "SW");
  await addStructureCategory(page, "Software", "Performance", "PERF");
  await expect(structureRow(page, "Performance")).toBeVisible();

  await page.getByRole("link", { name: "Requirements", exact: true }).click();
  await page.getByRole("button", { name: "New requirement" }).click();
  const createDialog = page.getByRole("dialog", { name: "New requirement" });
  await createDialog.getByPlaceholder("Name", { exact: true }).fill("Boot fast");
  await createDialog.getByRole("button", { name: "Create", exact: true }).click();

  await expect(page.getByRole("dialog", { name: "New requirement" })).not.toBeVisible();
  await expect(page.getByText("Boot fast")).toBeVisible();
});
