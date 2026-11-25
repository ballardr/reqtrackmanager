import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: project access is granted per project, not implied by organisation membership: a plain member
 * sees only the projects they hold a role on (one project in one organisation, or several across organisations),
 * and holding no org-admin/project-creator role means no ability to create projects.
 *
 * Personas:
 *  - StakeholderAlphaOnly: stakeholder on Alpha-1 only (member of Alpha, which alone does not grant Alpha-2).
 *  - MemberAlphaBeta: member on Alpha-1 and Beta-1 (two organisations), with no org_admin/project_creator role.
 */
test.describe("project access is scoped per-project, not per-org", () => {
  test("single-org, single-project user sees exactly one project", async ({ page }) => {
    await loginAs(page, PERSONAS.stakeholderAlpha.email);
    await page.goto("/projects");
    await expect(page.getByText(PROJECT_NAMES.alpha1)).toBeVisible();
    for (const name of [PROJECT_NAMES.alpha2, PROJECT_NAMES.beta1, PROJECT_NAMES.beta2, PROJECT_NAMES.gamma1, PROJECT_NAMES.gamma2]) {
      await expect(page.getByText(name)).toHaveCount(0);
    }
  });

  test("cross-org project user sees exactly the two projects granted, and cannot create new ones", async ({ page }) => {
    await loginAs(page, PERSONAS.memberAlphaBeta.email);
    await page.goto("/projects");

    await test.step("sees Alpha-1 and Beta-1, nothing else", async () => {
      await expect(page.getByText(PROJECT_NAMES.alpha1)).toBeVisible();
      await expect(page.getByText(PROJECT_NAMES.beta1)).toBeVisible();
      for (const name of [PROJECT_NAMES.alpha2, PROJECT_NAMES.beta2, PROJECT_NAMES.gamma1, PROJECT_NAMES.gamma2]) {
        await expect(page.getByText(name)).toHaveCount(0);
      }
    });

    await test.step("attempting to create a project is rejected server-side", async () => {
      // "New project" opens a Modal (style guide "Pattern: modal dialog for
      // entity create/rename") — scoped to it rather than the whole page.
      await page.getByRole("button", { name: "New project" }).click();
      const dialog = page.getByRole("dialog", { name: "New project" });
      await dialog.getByLabel("Name", { exact: true }).fill(`Should not be created ${Date.now()}`);
      await dialog.getByRole("button", { name: "Create", exact: true }).click();
      await expect(dialog.getByText(/only org admins or project creators/i)).toBeVisible();
    });
  });
});
