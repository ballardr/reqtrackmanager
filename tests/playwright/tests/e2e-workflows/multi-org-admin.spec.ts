import { expect, type Page, test } from "@playwright/test";

import { apiHeaders, installCleanupHook, loginAs, onCleanup, ORG_NAMES, PERSONAS, PROJECT_NAMES, searchProjects } from "./helpers";

/**
 * Job to be done: as an org admin of two organisations, I can create and
 * manage projects in either of them from the same account, but I have no
 * visibility into a third organisation I don't belong to.
 *
 * Persona: OrgAdminAlphaBeta (org_admin of Alpha + Beta; not a member of
 * Gamma at all).
 *
 * Project-list checks search by exact name (2026-10-05): the list pages at
 * 30, and an org merge-import can add a "<name> (imported)" copy that a
 * substring match also hits. The two projects it creates are archived
 * afterwards; they used to accumulate on every run.
 */
test.describe("org admin of two organisations", () => {
  installCleanupHook();

  /** Archives the just-created project (the page is on it) after the test. */
  function archiveCurrentProjectAfterTest(page: Page) {
    const projectId = page.url().match(/projects\/([0-9a-f-]+)/)![1];
    onCleanup(async (request) => {
      await request.post(`http://localhost:8000/api/v1/projects/${projectId}/archive`, {
        headers: await apiHeaders(request, PERSONAS.orgAdminAlphaBeta.email),
      });
    });
  }

  test("can create projects in both orgs, sees neither Gamma org nor its projects", async ({ page }) => {
    const newAlphaProject = `Alpha E2E Live ${Date.now()}`;
    const newBetaProject = `Beta E2E Live ${Date.now()}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    await test.step("existing Alpha and Beta seed projects are visible", async () => {
      await page.goto("/projects");
      for (const name of [PROJECT_NAMES.alpha1, PROJECT_NAMES.alpha2, PROJECT_NAMES.beta1, PROJECT_NAMES.beta2]) {
        await searchProjects(page, name);
        await expect(page.getByRole("link", { name, exact: true }).first()).toBeVisible();
      }
    });

    await test.step("create a new project in Alpha through the real UI form", async () => {
      // "New project" opens a Modal (style guide "Pattern: modal dialog for
      // entity create/rename"), portalled to document.body — scoped to it
      // rather than a bare page-wide query, same reasoning as the earlier
      // SidePanel conversion (a portalled layer doesn't sit in the same DOM
      // position an inline block would have).
      await page.getByRole("button", { name: "New project" }).click();
      const dialog = page.getByRole("dialog", { name: "New project" });
      // The org picker's options load asynchronously — wait for the actual
      // expected option text, not just "any options exist".
      await expect(dialog.getByRole("combobox").first()).toContainText(ORG_NAMES.alpha);
      await dialog.getByRole("combobox").first().selectOption({ label: ORG_NAMES.alpha });
      await dialog.getByLabel("Name", { exact: true }).fill(newAlphaProject);
      await dialog.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByRole("heading", { name: newAlphaProject })).toBeVisible();
      archiveCurrentProjectAfterTest(page);
    });

    await test.step("create a new project in Beta through the real UI form", async () => {
      await page.goto("/projects");
      await page.getByRole("button", { name: "New project" }).click();
      const dialog = page.getByRole("dialog", { name: "New project" });
      await expect(dialog.getByRole("combobox").first()).toContainText(ORG_NAMES.beta);
      await dialog.getByRole("combobox").first().selectOption({ label: ORG_NAMES.beta });
      await dialog.getByLabel("Name", { exact: true }).fill(newBetaProject);
      await dialog.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByRole("heading", { name: newBetaProject })).toBeVisible();
      archiveCurrentProjectAfterTest(page);
    });

    await test.step("both new projects now appear in the projects list", async () => {
      await page.goto("/projects");
      for (const name of [newAlphaProject, newBetaProject]) {
        await searchProjects(page, name);
        await expect(page.getByRole("link", { name, exact: true }).first()).toBeVisible();
      }
    });

    await test.step("Gamma's projects are not visible", async () => {
      for (const name of [PROJECT_NAMES.gamma1, PROJECT_NAMES.gamma2]) {
        await searchProjects(page, name);
        await expect(page.getByText(name)).toHaveCount(0);
      }
    });

    await test.step("Gamma's org admin page is not accessible", async () => {
      // /orgs is no longer linked from the nav (it duplicated the server
      // admin console for admins who could see both — see
      // docs/decisions.md) but the route itself is unchanged; this account
      // belongs to two orgs, so it lists them rather than redirecting.
      await page.goto("/orgs");
      await expect(page.getByText(ORG_NAMES.gamma)).toHaveCount(0);
    });
  });
});
