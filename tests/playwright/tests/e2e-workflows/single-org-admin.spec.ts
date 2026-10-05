import { expect, test } from "@playwright/test";

import { apiHeaders, installCleanupHook, loginAs, onCleanup, ORG_NAMES, PERSONAS, PROJECT_NAMES, searchProjects } from "./helpers";

/**
 * Job to be done: as the admin of a single organisation with no
 * relationship to any other org on the deployment, I can fully manage my
 * own org's projects while having zero visibility into unrelated orgs —
 * this is the multi-tenancy baseline every other persona in this suite is
 * compared against.
 *
 * Persona: OrgAdminGamma (org_admin of Gamma only — does not overlap with
 * OrgAdminAlphaBeta's orgs at all).
 *
 * Every project-list check searches by name (2026-10-04): the list pages at
 * 30 and Gamma has outgrown one page, so "visible" could fail and "absent"
 * could pass vacuously on page one alone. The project this creates is
 * archived afterwards; it used to accumulate in Gamma on every run.
 */
test.describe("admin of a separate, non-overlapping org", () => {
  installCleanupHook();

  test("manages Gamma, has zero visibility into Alpha/Beta", async ({ page }) => {
    const newGammaProject = `Gamma E2E Live ${Date.now()}`;

    await loginAs(page, PERSONAS.orgAdminGamma.email);

    await test.step("Gamma's seed projects are visible", async () => {
      await page.goto("/projects");
      for (const name of [PROJECT_NAMES.gamma1, PROJECT_NAMES.gamma2]) {
        await searchProjects(page, name);
        await expect(page.getByRole("link", { name, exact: true }).first()).toBeVisible();
      }
      await searchProjects(page, "");
    });

    await test.step("create a new project in Gamma (single-org account, no org picker shown)", async () => {
      // "New project" opens a Modal (style guide "Pattern: modal dialog for
      // entity create/rename") — scoped to it rather than the whole page.
      await page.getByRole("button", { name: "New project" }).click();
      const dialog = page.getByRole("dialog", { name: "New project" });
      // A single-org account gets no org picker in the new-project form
      // itself (ProjectListPage only renders one when orgs.length > 1).
      await dialog.getByLabel("Name", { exact: true }).fill(newGammaProject);
      await dialog.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByRole("heading", { name: newGammaProject })).toBeVisible();
      const projectId = page.url().match(/projects\/([0-9a-f-]+)/)![1];
      onCleanup(async (request) => {
        await request.post(`http://localhost:8000/api/v1/projects/${projectId}/archive`, {
          headers: await apiHeaders(request, PERSONAS.orgAdminGamma.email),
        });
      });
    });

    await test.step("Alpha and Beta are entirely invisible", async () => {
      await page.goto("/projects");
      for (const name of [PROJECT_NAMES.alpha1, PROJECT_NAMES.alpha2, PROJECT_NAMES.beta1, PROJECT_NAMES.beta2]) {
        await searchProjects(page, name);
        await expect(page.getByText(name)).toHaveCount(0);
      }
      // Belongs to exactly one org, so /orgs (no longer linked from the nav
      // — it duplicated the server admin console for admins who could see
      // it, see docs/decisions.md) redirects straight to Gamma's own admin
      // page rather than showing a list to choose from.
      await page.goto("/orgs");
      await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
      await expect(page.getByText(ORG_NAMES.alpha)).toHaveCount(0);
      await expect(page.getByText(ORG_NAMES.beta)).toHaveCount(0);
    });
  });
});
