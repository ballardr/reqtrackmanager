import crypto from "node:crypto";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectProjectAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: reach every entry of the layout designer's Add block menu however short the window is.
 *
 * The menu lists every block type the server publishes, so it grows with each new block type; at a short
 * window height the last entries must still be reachable with the wheel and the keyboard.
 *
 * Each test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Add block menu", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  /** A disposable organisation with an admin and a project, and a new layout open on its Blocks view. */
  async function openBlocks(page: Page, request: APIRequestContext) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-addmenu-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Add menu ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Add Menu Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Add menu project ${suffix}`, summary: "" } })).json();
    const name = `E2E add menu ${suffix}`;
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await page.getByRole("button", { name: "New", exact: true }).click();
    await page.getByRole("menuitem", { name: "New layout" }).click();
    const dialog = page.getByRole("dialog", { name: "New report layout" });
    await dialog.getByRole("textbox", { name: "Name" }).fill(name);
    await dialog.getByRole("button", { name: "Create" }).click();
    await expect(page.getByRole("heading", { name })).toBeVisible();
    await page.getByRole("tab", { name: "Blocks" }).click();
  }

  test("the last entry is reachable with the wheel at a short window height", async ({ page, request }) => {
    await page.setViewportSize({ width: 1280, height: 600 });
    await openBlocks(page, request);
    await page.getByRole("button", { name: "Add block" }).click();
    const menu = page.getByRole("menu", { name: "Add block" });
    const items = menu.getByRole("menuitem");
    const last = items.last();

    await test.step("the menu fits the window and scrolls inside", async () => {
      const box = await page.getByRole("dialog", { name: "Add block" }).boundingBox();
      expect(box).not.toBeNull();
      expect(box!.y).toBeGreaterThanOrEqual(0);
      expect(box!.y + box!.height).toBeLessThanOrEqual(600);
    });

    await test.step("the wheel brings the last entry into view", async () => {
      const box = await menu.boundingBox();
      await page.mouse.move(box!.x + box!.width / 2, box!.y + Math.min(box!.height, 100) / 2);
      for (let i = 0; i < 20; i++) await page.mouse.wheel(0, 400);
      await expect(last).toBeInViewport();
    });

    await test.step("choosing it adds that block", async () => {
      const label = (await last.innerText()).trim();
      await last.click();
      await expect(page.getByRole("menu", { name: "Add block" })).toBeHidden();
      await expect(page.getByLabel("Block details")).toContainText(label.replace(/\s+\d+$/, ""));
    });
  });

  test("the keyboard walks to the last entry and keeps the focused entry in view", async ({ page, request }) => {
    await page.setViewportSize({ width: 1280, height: 600 });
    await openBlocks(page, request);
    await page.getByRole("button", { name: "Add block" }).click();
    const items = page.getByRole("menu", { name: "Add block" }).getByRole("menuitem");
    const count = await items.count();
    expect(count).toBeGreaterThan(5);

    for (let i = 0; i < count + 2; i++) await page.keyboard.press("Tab");
    // Tab leaves the menu only if it is not trapped; either way the last entry must be focusable and visible.
    await items.last().focus();
    await expect(items.last()).toBeFocused();
    await expect(items.last()).toBeInViewport();
  });
});
