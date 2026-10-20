import { expect, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectProjectAdminGroup, setOrgModuleAvailability, selectOrgAdminGroup } from "../../e2e-workflows/helpers";

// Deletes this file's disposable org after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API_BASE_URL = "http://localhost:8000";

/** Type names render as editable `<input>` values (the `DefinitionList` rename field). */
function inputWithValue(page: Page, value: string) {
  return page.locator(`input.input[value="${value}"]:not([placeholder])`);
}

/**
 * Job to be done: a project administrator can hide an organisation-default Pain Point type in
 * one project (its delete button), existing Pain Points keep the type, the type is not offered
 * on a new Pain Point, another project is unaffected, and "Add organisation defaults" brings it
 * back. Uses a disposable org, so it neither depends on nor changes shared seed data.
 */
test.describe("Context & Strategy: hide and restore organisation Pain Point types", () => {
  test("hides an org default in one project and adds it back", async ({ page }) => {
    const suffix = Date.now();
    const adminEmail = `e2e-pp-hide-admin-${suffix}@example.com`;

    const serverAdminToken = (
      await (await page.request.post(`${API_BASE_URL}/api/v1/auth/login`, {
        data: { email: "admin@example.com", password: "ChangeMe123!" },
      })).json()
    ).access_token;
    const serverAdminHeaders = { Authorization: `Bearer ${serverAdminToken}` };
    const org = await (
      await page.request.post(`${API_BASE_URL}/api/v1/orgs`, { headers: serverAdminHeaders, data: { name: `E2E PP Hide Org ${suffix}` } })
    ).json();
    deleteOrgOnCleanup({ id: org.id });
    await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users`, {
      headers: serverAdminHeaders,
      data: { email: adminEmail, display_name: "E2E PP Hide Admin", password: PASSWORD, role: "org_admin" },
    });

    await loginAs(page, adminEmail, PASSWORD);
    const adminToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const adminHeaders = { Authorization: `Bearer ${adminToken}` };
    const createProject = async (name: string) =>
      (await (await page.request.post(`${API_BASE_URL}/api/v1/projects`, {
        headers: adminHeaders, data: { organization_id: org.id, name, summary: "" },
      })).json()) as { id: string };
    const hidingProject = await createProject(`E2E PP Hide Project ${suffix}`);
    const otherProject = await createProject(`E2E PP Other Project ${suffix}`);

    await page.goto("/orgs");
    await selectOrgAdminGroup(page, "Modules");
    await setOrgModuleAvailability(page, "Context & Strategy", "default_on");

    // A Pain Point of type "User" exists before it is hidden: it must keep showing it.
    const types = (await (await page.request.get(
      `${API_BASE_URL}/api/v1/projects/${hidingProject.id}/modules/context_strategy/pain-point-types`, { headers: adminHeaders },
    )).json()) as { id: string; name: string }[];
    const userType = types.find((t) => t.name === "User")!;
    const painPointTitle = `Existing pain point ${suffix}`;
    expect((await page.request.post(
      `${API_BASE_URL}/api/v1/projects/${hidingProject.id}/modules/context_strategy/pain-points`,
      { headers: adminHeaders, data: { title: painPointTitle, description: "d", pain_point_type_id: userType.id } },
    )).ok()).toBeTruthy();

    await test.step("hide the User type: confirm, and it leaves the list", async () => {
      await page.goto(`/projects/${hidingProject.id}/admin`);
      await selectProjectAdminGroup(page, "Pain Point Types");
      await expect(page.getByRole("button", { name: /Add organisation defaults/ })).toHaveCount(0);

      const userRow = inputWithValue(page, "User").locator("xpath=ancestor::div[contains(@class,'stack')][1]");
      await userRow.getByRole("button", { name: "Hide Pain Point type in this project" }).click();
      const dialog = page.getByRole("dialog", { name: 'Hide "User" in this project?' });
      await dialog.getByRole("button", { name: "Hide" }).click();

      await expect(inputWithValue(page, "User")).toHaveCount(0);
      await expect(inputWithValue(page, "Market")).toBeVisible();
      await expect(page.getByRole("button", { name: "Add organisation defaults (1)" })).toBeVisible();
    });

    await test.step("a new Pain Point cannot pick it, the existing one keeps it, the other project is unaffected", async () => {
      await page.goto(`/projects/${hidingProject.id}/modules/context_strategy/pain-points`);
      await expect(page.getByRole("row", { name: new RegExp(painPointTitle) }).getByText("User", { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "New Pain Point" }).click();
      const typeSelect = page.getByRole("dialog", { name: "New Pain Point" }).getByLabel("Type", { exact: true });
      await expect(typeSelect.locator("option", { hasText: "Market" })).toHaveCount(1);
      await expect(typeSelect.locator("option", { hasText: "User" })).toHaveCount(0);

      const otherTypes = (await (await page.request.get(
        `${API_BASE_URL}/api/v1/projects/${otherProject.id}/modules/context_strategy/pain-point-types`, { headers: adminHeaders },
      )).json()) as { name: string }[];
      expect(otherTypes.map((t) => t.name)).toContain("User");
    });

    await test.step("Add organisation defaults brings it back", async () => {
      await page.goto(`/projects/${hidingProject.id}/admin`);
      await selectProjectAdminGroup(page, "Pain Point Types");
      await page.getByRole("button", { name: "Add organisation defaults (1)" }).click();
      const dialog = page.getByRole("dialog", { name: "Add organisation defaults" });
      await expect(dialog.getByRole("checkbox", { name: "User" })).toBeChecked();
      await dialog.getByRole("button", { name: "Add 1 default" }).click();

      await expect(inputWithValue(page, "User")).toBeVisible();
      await expect(page.getByRole("button", { name: /Add organisation defaults/ })).toHaveCount(0);
    });
  });
});
