import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: project access is granted per-project, not implied by org
 * membership — a plain org member sees only the specific projects they've
 * been given a role on, whether that's one project in one org or several
 * projects spanning multiple orgs, and holding no org-admin/project-creator
 * role means no ability to create new projects, full stop.
 *
 * Personas:
 *  - StakeholderAlphaOnly: stakeholder on Alpha-1 only (member of Alpha org,
 *    but that alone doesn't grant Alpha-2 access).
 *  - MemberAlphaBeta: member on Alpha-1 *and* Beta-1 (two different orgs),
 *    with no org_admin/project_creator role anywhere.
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
      await page.getByRole("button", { name: "New project" }).click();
      await page.getByPlaceholder("Name").fill(`Should not be created ${Date.now()}`);
      await page.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByText(/only org admins or project creators/i)).toBeVisible();
    });
  });
});
