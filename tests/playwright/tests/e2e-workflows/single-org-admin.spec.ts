import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: as the admin of a single organisation with no
 * relationship to any other org on the deployment, I can fully manage my
 * own org's projects while having zero visibility into unrelated orgs —
 * this is the multi-tenancy baseline every other persona in this suite is
 * compared against.
 *
 * Persona: OrgAdminGamma (org_admin of Gamma only — does not overlap with
 * OrgAdminAlphaBeta's orgs at all).
 */
test.describe("admin of a separate, non-overlapping org", () => {
  test("manages Gamma, has zero visibility into Alpha/Beta", async ({ page }) => {
    const newGammaProject = `Gamma E2E Live ${Date.now()}`;

    await loginAs(page, PERSONAS.orgAdminGamma.email);

    await test.step("Gamma's seed projects are visible", async () => {
      await page.goto("/projects");
      await expect(page.getByText(PROJECT_NAMES.gamma1)).toBeVisible();
      await expect(page.getByText(PROJECT_NAMES.gamma2)).toBeVisible();
    });

    await test.step("create a new project in Gamma (single-org account, no org picker shown)", async () => {
      await page.getByRole("button", { name: "New project" }).click();
      // A single-org account gets no org picker in the new-project form
      // itself (ProjectListPage only renders one when orgs.length > 1) —
      // the two comboboxes still on the page are the unrelated role/stage
      // filters, always present regardless of org count.
      await page.getByPlaceholder("Name").fill(newGammaProject);
      await page.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByRole("heading", { name: newGammaProject })).toBeVisible();
    });

    await test.step("Alpha and Beta are entirely invisible", async () => {
      await page.goto("/projects");
      for (const name of [PROJECT_NAMES.alpha1, PROJECT_NAMES.alpha2, PROJECT_NAMES.beta1, PROJECT_NAMES.beta2]) {
        await expect(page.getByText(name)).toHaveCount(0);
      }
      await page.getByRole("link", { name: "Organisations", exact: true }).click();
      await expect(page.getByText(ORG_NAMES.alpha)).toHaveCount(0);
      await expect(page.getByText(ORG_NAMES.beta)).toHaveCount(0);
    });
  });
});
