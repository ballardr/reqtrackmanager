import { expect, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const apiBaseUrl = "http://localhost:8000";

/**
 * Job to be done: a user orders the Project nav section and moves rarely used items behind
 * "More"; the choice follows them across projects, can be overridden for one project, and never
 * hides the page they are on (docs/plans/platform-enhancements-2026-10-plan.md Phase 4).
 *
 * Runs against a disposable org with its own org admin and two projects, so the preferences it
 * writes belong to a throwaway user and cannot reorder anyone else's nav.
 */
async function setupOrgWithTwoProjects(page: Page) {
  const suffix = Date.now();
  const adminEmail = `e2e-projnav-admin-${suffix}@example.com`;
  const serverAdminToken = (
    await (
      await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
        data: { email: "admin@example.com", password: "ChangeMe123!" },
      })
    ).json()
  ).access_token;
  const serverAdminHeaders = { Authorization: `Bearer ${serverAdminToken}` };
  const org = await (
    await page.request.post(`${apiBaseUrl}/api/v1/orgs`, {
      headers: serverAdminHeaders, data: { name: `E2E ProjNav Org ${suffix}` },
    })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: serverAdminHeaders,
    data: { email: adminEmail, display_name: "E2E ProjNav Admin", password: PASSWORD, role: "org_admin" },
  });
  const adminToken = (
    await (await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: adminEmail, password: PASSWORD } })).json()
  ).access_token;
  const createProject = async (name: string): Promise<{ id: string }> =>
    (
      await page.request.post(`${apiBaseUrl}/api/v1/projects`, {
        headers: { Authorization: `Bearer ${adminToken}` },
        data: { organization_id: org.id, name: `${name} ${suffix}`, summary: "E2E nav project." },
      })
    ).json();
  const projectA = await createProject("E2E ProjNav A");
  const projectB = await createProject("E2E ProjNav B");
  await loginAs(page, adminEmail, PASSWORD);
  return { projectA, projectB };
}

/** Names of the nav rail's Project-section links, top to bottom (the Global section starts at "Projects"). */
async function navLinkNames(page: Page): Promise<string[]> {
  const all = await page
    .getByRole("navigation")
    .getByRole("link")
    .evaluateAll((links) => links.map((link) => link.getAttribute("aria-label") ?? ""));
  return all.slice(0, all.indexOf("Projects"));
}

/** The History item's label under default terminology. */
const HISTORY = "Project history";

const navLink = (page: Page, name: string) => page.getByRole("navigation").getByRole("link", { name, exact: true });
const editor = (page: Page) => page.getByRole("dialog", { name: "Customise navigation" });

async function openEditor(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Customise navigation" }).click();
  await expect(editor(page)).toBeVisible();
}

/** Clicks Save and waits for the preference PATCH to settle (an immediate reload would abort it). */
async function saveEditor(page: Page): Promise<void> {
  await Promise.all([
    page.waitForResponse((r) => r.url().includes("/auth/me/preferences") && r.request().method() === "PATCH"),
    editor(page).getByRole("button", { name: "Save" }).click(),
  ]);
  await expect(editor(page)).toBeHidden();
}

test.describe("project nav: personal order, More, per-project override", () => {
  test("reorder and More persist across reload and projects; the active page is never hidden; reset restores the default", async ({ page }) => {
    const { projectA, projectB } = await setupOrgWithTwoProjects(page);
    await page.goto(`/projects/${projectA.id}`);
    const defaultOrder = await navLinkNames(page);
    expect(defaultOrder.indexOf("Reports")).toBeGreaterThan(-1);

    await test.step("pinned items cannot be moved to More", async () => {
      await openEditor(page);
      await expect(editor(page).getByRole("button", { name: "Move Overview to More" })).toHaveCount(0);
      await expect(editor(page).getByRole("button", { name: "Move Project admin to More" })).toHaveCount(0);
      await expect(editor(page).getByRole("button", { name: "Move Reports to More" })).toBeVisible();
    });

    await test.step("move Reports up one place and Project history to More, then save for all projects", async () => {
      await editor(page).getByRole("button", { name: "Move Reports up" }).click();
      await editor(page).getByRole("button", { name: "Move Project history to More" }).click();
      await saveEditor(page);
      await expect(page.getByText("Navigation saved")).toBeVisible();

      const reordered = await navLinkNames(page);
      expect(reordered.indexOf("Reports")).toBe(defaultOrder.indexOf("Reports") - 1);
      await expect(navLink(page, HISTORY)).toHaveCount(0);
      await page.getByRole("navigation").getByRole("button", { name: "More" }).click();
      await expect(navLink(page, HISTORY)).toBeVisible();
    });

    await test.step("the choice survives a reload and applies to the other project", async () => {
      await page.reload();
      await expect(navLink(page, HISTORY)).toHaveCount(0);
      await page.goto(`/projects/${projectB.id}`);
      await expect(navLink(page, HISTORY)).toHaveCount(0);
      expect((await navLinkNames(page)).indexOf("Reports")).toBe(defaultOrder.indexOf("Reports") - 1);
    });

    await test.step("landing on a hidden item's page shows its link without opening More", async () => {
      await page.goto(`/projects/${projectB.id}/history`);
      await expect(navLink(page, HISTORY)).toBeVisible();
      await expect(navLink(page, HISTORY)).toHaveClass(/active/);
    });

    await test.step("reset to default restores the product order", async () => {
      await openEditor(page);
      await editor(page).getByRole("button", { name: "Reset to default" }).click();
      await saveEditor(page);
      await expect(navLink(page, HISTORY)).toBeVisible();
      expect(await navLinkNames(page)).toEqual(defaultOrder);
    });
  });

  test("a per-project override applies to one project only and can be removed", async ({ page }) => {
    const { projectA, projectB } = await setupOrgWithTwoProjects(page);
    await page.goto(`/projects/${projectA.id}`);

    await test.step("save a layout for this project only", async () => {
      await openEditor(page);
      await editor(page).getByRole("radio", { name: "Only this project" }).check();
      await editor(page).getByRole("button", { name: "Move Files to More" }).click();
      await saveEditor(page);
      await expect(navLink(page, "Files")).toHaveCount(0);
    });

    await test.step("the other project is unaffected", async () => {
      await page.goto(`/projects/${projectB.id}`);
      await expect(navLink(page, "Files")).toBeVisible();
      await page.goto(`/projects/${projectA.id}`);
      await expect(navLink(page, "Files")).toHaveCount(0);
    });

    await test.step("removing the override restores the default for this project", async () => {
      await openEditor(page);
      await expect(editor(page).getByRole("radio", { name: "Only this project" })).toBeChecked();
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/auth/me/preferences") && r.request().method() === "PATCH"),
        editor(page).getByRole("button", { name: "Remove this project's own layout" }).click(),
      ]);
      await expect(page.getByText("This project's own layout removed")).toBeVisible();
      await expect(navLink(page, "Files")).toBeVisible();
    });
  });

  test("a refused save shows the server's error, keeps the editor open, and changes nothing", async ({ page }) => {
    const { projectA } = await setupOrgWithTwoProjects(page);
    await page.goto(`/projects/${projectA.id}`);
    const before = await navLinkNames(page);

    // Fill the user's own bag to the key limit through the API, so the real bound rejects the save.
    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    expect(token).toBeTruthy();
    const filler = Object.fromEntries(Array.from({ length: 200 }, (_, i) => [`e2e_filler_${i}`, true]));
    const fill = await page.request.patch(`${apiBaseUrl}/api/v1/auth/me/preferences`, {
      headers: { Authorization: `Bearer ${token}` }, data: { ui_preferences: filler },
    });
    expect(fill.ok()).toBeTruthy();

    await openEditor(page);
    await editor(page).getByRole("button", { name: "Move Files to More" }).click();
    await Promise.all([
      page.waitForResponse((r) => r.url().includes("/auth/me/preferences") && r.request().method() === "PATCH" && r.status() === 422),
      editor(page).getByRole("button", { name: "Save" }).click(),
    ]);
    await expect(page.getByText("UI preferences are limited to 200 keys.")).toBeVisible();
    await expect(page.getByText("Navigation saved")).toHaveCount(0);
    await expect(editor(page)).toBeVisible();
    await editor(page).getByRole("button", { name: "Cancel" }).click();
    expect(await navLinkNames(page)).toEqual(before);
  });

  test("with the rail collapsed, More opens as a popover and customising is its own row", async ({ page }) => {
    const { projectA } = await setupOrgWithTwoProjects(page);
    await page.goto(`/projects/${projectA.id}`);

    await test.step("move Reports to More while expanded", async () => {
      await openEditor(page);
      await editor(page).getByRole("button", { name: "Move Reports to More" }).click();
      await saveEditor(page);
    });

    await test.step("collapsed rail: More is a popover whose links navigate and close it", async () => {
      await page.getByRole("button", { name: "Collapse navigation" }).click();
      const more = page.getByRole("navigation").getByRole("button", { name: "More" });
      await more.click();
      const popover = page.getByRole("dialog", { name: "More" });
      await expect(popover.getByRole("link", { name: "Reports" })).toBeVisible();
      await popover.getByRole("link", { name: "Reports" }).click();
      await page.waitForURL(/\/reports$/);
      await expect(popover).toBeHidden();
    });

    await test.step("collapsed rail still offers Customise navigation", async () => {
      await page.getByRole("navigation").getByRole("button", { name: "Customise navigation" }).click();
      await expect(editor(page)).toBeVisible();
      await editor(page).getByRole("button", { name: "Reset to default" }).click();
      await saveEditor(page);
      await page.getByRole("button", { name: "Expand navigation" }).click();
    });
  });
});
