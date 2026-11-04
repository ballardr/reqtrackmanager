import crypto from "node:crypto";

import { expect, type APIRequestContext, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, saveNewVersion, selectProjectAdminGroup, openDesignerTextView } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: save a long report layout without scrolling to the end of it to find the Save button.
 *
 * Each test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Report layout designer Save bar", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  test("Save stays in view at the top of a long layout, and a second one appears at the foot only when it is long", async ({ page, request }) => {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-save-bar-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Save Bar ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Save Bar Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Save bar project ${suffix}`, summary: "" } })).json();
    const name = `E2E save bar layout ${suffix}`;
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await page.getByRole("button", { name: "New", exact: true }).click();
    await page.getByRole("menuitem", { name: "New layout" }).click();
    const dialog = page.getByRole("dialog", { name: "New report layout" });
    await dialog.getByRole("textbox", { name: "Name" }).fill(name);
    await dialog.getByRole("button", { name: "Create" }).click();
    await expect(page.getByRole("heading", { name })).toBeVisible();

    const save = page.getByRole("button", { name: "Save new version" });
    await openDesignerTextView(page);
    const editor = page.getByRole("textbox", { name: "Layout text" });

    await test.step("a short layout has a single Save", async () => {
      await editor.fill("@layout document\n\n@heading Short\n");
      await expect(page.getByText("The text is valid.")).toBeVisible();
      await expect(save).toHaveCount(1);
    });

    await test.step("a long layout has a second Save at the foot", async () => {
      const headings = Array.from({ length: 150 }, (_, i) => `@heading Section ${i + 1}\n`).join("\n");
      await editor.fill(`@layout document\n\n${headings}`);
      await expect(page.getByText("The text is valid.")).toBeVisible();
      await expect(save).toHaveCount(2);
    });

    await test.step("the top Save is still in view at the bottom of the page, and saves", async () => {
      await page.mouse.wheel(0, 100000);
      await expect(save.first()).toBeInViewport();
      await expect(save.last()).toBeInViewport();
      await saveNewVersion(page, "Long layout");
      await expect(page.getByText("Version 2", { exact: true })).toBeVisible();
      await expect(page.getByText("Unsaved changes")).toHaveCount(0);
    });

    await test.step("a problem is explained beside the pinned Save", async () => {
      await editor.fill("BROKEN @layout document\n");
      await expect(page.getByText(/^Fix \d+ problems? to save$/)).toBeVisible();
      await expect(save.first()).toBeDisabled();
    });
  });
});
