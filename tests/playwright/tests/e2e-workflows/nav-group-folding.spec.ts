import { expect, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const apiBaseUrl = "http://localhost:8000";

/**
 * Job to be done: a person folds a navigation group to shorten the rail; the choice is kept across a reload, and
 * opening a page inside a folded group opens it, so the current entry is never hidden.
 *
 * Runs as a disposable organisation administrator, so the preference it writes belongs to a throwaway user and
 * cannot fold the rail of the shared personas other specs click through.
 */
async function signInAsDisposableAdmin(page: Page): Promise<void> {
  const suffix = Date.now();
  const adminEmail = `e2e-navgroup-admin-${suffix}@example.com`;
  const serverAdminToken = (
    await (
      await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
        data: { email: "admin@example.com", password: "ChangeMe123!" },
      })
    ).json()
  ).access_token;
  const headers = { Authorization: `Bearer ${serverAdminToken}` };
  const org = await (
    await page.request.post(`${apiBaseUrl}/api/v1/orgs`, { headers, data: { name: `E2E NavGroup Org ${suffix}` } })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers,
    data: { email: adminEmail, display_name: "E2E NavGroup Admin", password: PASSWORD, role: "org_admin" },
  });
  await loginAs(page, adminEmail, PASSWORD);
}

const globalToggle = (page: Page) => page.getByRole("navigation").getByRole("button", { name: "Global", exact: true });
const rail = (page: Page) => page.getByRole("navigation");

/**
 * Clicks the group heading and waits for the save of that group's own preference to settle (an immediate reload
 * would abort it). The wait names the key, so another preference write cannot satisfy it first.
 */
async function toggleGlobal(page: Page): Promise<void> {
  await Promise.all([
    page.waitForResponse(
      (r) => r.url().includes("/auth/me/preferences") && r.request().method() === "PATCH"
        && (r.request().postData() ?? "").includes("nav_group_folded:global"),
    ),
    globalToggle(page).click(),
  ]);
}

test.describe("navigation groups fold", () => {
  test("a folded group stays folded across a reload and opens when a page inside it is opened", async ({ page }) => {
    await signInAsDisposableAdmin(page);
    // A page outside the Global group, so folding it hides nothing the person is on.
    await page.goto("/preferences");
    await expect(globalToggle(page)).toHaveAttribute("aria-expanded", "true");
    await expect(rail(page).getByRole("link", { name: "Organisation settings" })).toBeVisible();

    await toggleGlobal(page);
    await expect(globalToggle(page)).toHaveAttribute("aria-expanded", "false");
    await expect(rail(page).getByRole("link", { name: "Organisation settings" })).toBeHidden();

    await page.reload();
    await expect(globalToggle(page)).toHaveAttribute("aria-expanded", "false");
    await expect(rail(page).getByRole("link", { name: "Organisation settings" })).toBeHidden();

    // Opening a page of the group unfolds it, and the active entry is shown.
    await page.goto("/projects");
    await expect(globalToggle(page)).toHaveAttribute("aria-expanded", "true");
    await expect(rail(page).getByRole("link", { name: "Projects", exact: true })).toHaveClass(/active/);
    await expect(rail(page).getByRole("link", { name: "Organisation settings" })).toBeVisible();
  });

  test("folding the group that holds the current page keeps the current entry", async ({ page }) => {
    await signInAsDisposableAdmin(page);
    await page.goto("/projects");
    await toggleGlobal(page);
    await expect(globalToggle(page)).toHaveAttribute("aria-expanded", "false");
    await expect(rail(page).getByRole("link", { name: "Projects", exact: true })).toBeVisible();
    await expect(rail(page).getByRole("link", { name: "Organisation settings" })).toBeHidden();
  });
});
