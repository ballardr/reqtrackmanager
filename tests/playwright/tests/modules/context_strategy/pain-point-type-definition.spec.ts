import { expect, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectProjectAdminGroup, setOrgModuleAvailability, selectOrgAdminGroup } from "../../e2e-workflows/helpers";

// Deletes this file's disposable org after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API_BASE_URL = "http://localhost:8000";

/**
 * Job to be done: an organisation administrator writes what belongs under a Pain Point type, and a person
 * raising a Pain Point sees that text under the Type picker; a project can replace it for itself, and
 * clearing the project's text brings the organisation's back. Uses a disposable org.
 */
test.describe("Context & Strategy: Pain Point type definitions", () => {
  test("org definition shows in the picker, a project overrides it, clearing reverts", async ({ page }) => {
    const suffix = Date.now();
    const adminEmail = `e2e-pp-def-admin-${suffix}@example.com`;
    const orgText = `Where buyers and competitors meet ${suffix}`;
    const projectText = `Our paying customers ${suffix}`;

    const serverAdminToken = (
      await (await page.request.post(`${API_BASE_URL}/api/v1/auth/login`, {
        data: { email: "admin@example.com", password: "ChangeMe123!" },
      })).json()
    ).access_token;
    const serverAdminHeaders = { Authorization: `Bearer ${serverAdminToken}` };
    const org = await (
      await page.request.post(`${API_BASE_URL}/api/v1/orgs`, { headers: serverAdminHeaders, data: { name: `E2E PP Def Org ${suffix}` } })
    ).json();
    deleteOrgOnCleanup({ id: org.id });
    await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users`, {
      headers: serverAdminHeaders,
      data: { email: adminEmail, display_name: "E2E PP Def Admin", password: PASSWORD, role: "org_admin" },
    });

    await loginAs(page, adminEmail, PASSWORD);
    const adminToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const adminHeaders = { Authorization: `Bearer ${adminToken}` };
    const project = (await (await page.request.post(`${API_BASE_URL}/api/v1/projects`, {
      headers: adminHeaders, data: { organization_id: org.id, name: `E2E PP Def Project ${suffix}`, summary: "" },
    })).json()) as { id: string };

    await page.goto("/orgs");
    await selectOrgAdminGroup(page, "Modules");
    await setOrgModuleAvailability(page, "Context & Strategy", "default_on");

    const openNewPainPoint = async () => {
      await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points`);
      await page.getByRole("button", { name: "New Pain Point" }).click();
      const dialog = page.getByRole("dialog", { name: "New Pain Point" });
      await dialog.getByLabel("Type", { exact: true }).selectOption({ label: "Market" });
      return dialog;
    };
    const definitionBox = (scope: Page, name: string) => scope.getByRole("textbox", { name, exact: true });

    await test.step("the organisation writes a definition for Market", async () => {
      await page.goto("/orgs");
      await selectOrgAdminGroup(page, "Pain Point Types");
      const box = definitionBox(page, "Pain Point type definition").first();
      await box.fill(orgText);
      await page.getByRole("button", { name: "Rename" }).first().click();
      await expect(page.getByRole("textbox", { name: "Pain Point type definition" }).first()).toHaveValue(orgText);
    });

    await test.step("the picker shows it under the Type field", async () => {
      const dialog = await openNewPainPoint();
      await expect(dialog.getByText(orgText)).toBeVisible();
    });

    await test.step("the project replaces it for itself", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Pain Point Types");
      const box = definitionBox(page, "Project Pain Point type definition").first();
      await expect(box).toHaveValue(orgText);
      await box.fill(projectText);
      await page.getByRole("button", { name: "Rename" }).first().click();
      await expect(page.getByText("Org default (overridden)")).toBeVisible();

      const dialog = await openNewPainPoint();
      await expect(dialog.getByText(projectText)).toBeVisible();
      await expect(dialog.getByText(orgText)).toHaveCount(0);
    });

    await test.step("clearing the project's text brings the organisation's back", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Pain Point Types");
      const box = definitionBox(page, "Project Pain Point type definition").first();
      await box.fill("");
      await page.getByRole("button", { name: "Rename" }).first().click();

      const dialog = await openNewPainPoint();
      await expect(dialog.getByText(orgText)).toBeVisible();
    });
  });
});
