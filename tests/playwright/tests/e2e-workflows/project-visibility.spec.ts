import { expect, type Locator, type Page, test } from "@playwright/test";

import { apiHeaders, clickAndAwaitSave, deleteOrgOnCleanup, installCleanupHook, loginAs, logout, PASSWORD } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/** The hierarchical-projects "Parent project" <select> shares every form
 * this spec's own "Visibility" <select> lives on. A wrapping <label>'s
 * computed accessible name flattens in all descendant text, including
 * every <option> — so once "Parent project" lists every project in the
 * org, a leftover/dynamically-named project (this spec's own included,
 * since it names its throwaway project `Org Wide Visibility ${Date.now()}`,
 * repeated back-to-back without an org wipe between runs per this
 * project's own idempotency rule) can make its accessible name contain
 * "Visibility" too, and getByLabel("Visibility") ambiguous. Located
 * structurally instead — the Visibility select is the one whose own
 * <option> list contains "Only specified" (never a project name) —
 * rather than by label, so this doesn't depend on a debris-free org. */
function visibilitySelect(scope: Page | Locator): Locator {
  return scope.locator("select").filter({ hasText: "Only specified" });
}

/**
 * Job to be done: a project can be marked "Org-wide visibility" so every
 * member of its organisation gets automatic read access with no explicit
 * user/group assignment — as opposed to the default "Only specified" mode,
 * where access requires one. Covers both places the toggle lives (the "New
 * project" creation form, and Project Admin's settings tab) and confirms
 * the grant is read-only (never implies management rights) and reversible.
 *
 * Runs in its own disposable organisation, with a disposable org admin and
 * a disposable plain member holding no project role (2026-10-04). It used
 * the shared Alpha org and `stakeholderAlpha`, so while it ran, its
 * org-wide project was visible to that shared persona and broke other
 * specs' exact counts running in parallel (org-overview.spec.ts) — a
 * cross-spec race no cleanup can prevent.
 */
test.describe("project visibility: org-wide vs only specified", () => {
  test("org-wide visibility grants read access with no explicit role, and is reversible", async ({ page, request }) => {
    const suffix = Date.now();
    const projectName = `Org Wide Visibility ${suffix}`;
    const adminEmail = `e2e-visibility-admin-${suffix}@example.com`;
    const memberEmail = `e2e-visibility-member-${suffix}@example.com`;

    await test.step("set up a disposable org with an admin and a role-less member", async () => {
      const serverAdmin = await apiHeaders(request, "admin@example.com", "ChangeMe123!");
      const org = await (await request.post("http://localhost:8000/api/v1/orgs", {
        headers: serverAdmin, data: { name: `E2E Visibility Org ${suffix}` },
      })).json();
      deleteOrgOnCleanup({ id: org.id });
      for (const [email, role] of [[adminEmail, "org_admin"], [memberEmail, "member"]]) {
        const resp = await request.post(`http://localhost:8000/api/v1/orgs/${org.id}/users`, {
          headers: serverAdmin, data: { email, display_name: email.split("@")[0], password: PASSWORD, role },
        });
        expect(resp.ok()).toBeTruthy();
      }
    });

    await test.step("org admin creates a new project with Org-wide visibility set at creation", async () => {
      await loginAs(page, adminEmail);
      await page.goto("/projects");
      // "New project" opens a Modal (style guide "Pattern: modal dialog for
      // entity create/rename") — scoped to it rather than the whole page.
      // A single-org admin gets no organisation picker.
      await page.getByRole("button", { name: "New project" }).click();
      const dialog = page.getByRole("dialog", { name: "New project" });
      await dialog.getByLabel("Name", { exact: true }).fill(projectName);
      await visibilitySelect(dialog).selectOption("org_wide");
      await dialog.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByRole("heading", { name: projectName })).toBeVisible();
    });

    await test.step("Project Admin's settings tab reflects Org-wide visibility", async () => {
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await expect(visibilitySelect(page)).toHaveValue("org_wide");
    });

    await test.step("a plain org member with no explicit role sees and can open the project", async () => {
      await logout(page);
      await loginAs(page, memberEmail);
      await page.goto("/projects");
      await expect(page.getByText(projectName)).toBeVisible();
      await page.getByText(projectName).click();
      await expect(page.getByRole("heading", { name: projectName })).toBeVisible();
    });

    await test.step("org admin switches it back to Only specified", async () => {
      await logout(page);
      await loginAs(page, adminEmail);
      await page.goto("/projects");
      await page.getByText(projectName).click();
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await visibilitySelect(page).selectOption("only_specified");
      await clickAndAwaitSave(page, page.getByRole("button", { name: "Save settings" }), "/api/v1/projects/");
      await expect(visibilitySelect(page)).toHaveValue("only_specified");
    });

    await test.step("the same org member no longer sees the project", async () => {
      await logout(page);
      await loginAs(page, memberEmail);
      await page.goto("/projects");
      await expect(page.getByText(projectName)).toHaveCount(0);
    });
  });
});
