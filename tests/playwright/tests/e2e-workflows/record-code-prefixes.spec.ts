import { expect, type APIRequestContext, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: an organisation names its records its own way (`TSK-002` for an action, not `ACT-002`), and one
 * project can differ from the organisation; the change applies to records created afterwards and a number is never
 * reused.
 *
 * Covers: an organisation administrator choosing a prefix for actions in Organisation Admin, a project inheriting it
 * (and saying so), the project manager overriding it in Project Admin and returning to the inherited value, and a
 * refused prefix (one another record type already uses) showing the server's message.
 *
 * Each test builds its own organisation, so none depends on state left by another test.
 */

const apiBaseUrl = "http://localhost:8000";

interface World {
  orgId: string;
  adminEmail: string;
  headers: { Authorization: string };
  projectId: string;
  actionTypeId: string;
}

async function createWorld(request: APIRequestContext, label: string): Promise<World> {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  const adminEmail = `e2e-${label}-admin-${suffix}@example.com`;
  const serverToken = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: "admin@example.com", password: "ChangeMe123!" } })).json()
  ).access_token;
  const serverHeaders = { Authorization: `Bearer ${serverToken}` };
  const org = await (
    await request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: serverHeaders, data: { name: `Record prefixes ${label} ${suffix}` } })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  await request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders,
    data: { email: adminEmail, display_name: "E2E Record Prefix Admin", password: PASSWORD, role: "org_admin" },
  });
  const token = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: adminEmail, password: PASSWORD } })).json()
  ).access_token;
  const headers = { Authorization: `Bearer ${token}` };
  const project = await (
    await request.post(`${apiBaseUrl}/api/v1/projects`, { headers, data: { organization_id: org.id, name: "Prefix Project", summary: "" } })
  ).json();
  const actionTypes = await (await request.get(`${apiBaseUrl}/api/v1/projects/${project.id}/action-types`, { headers })).json();
  return { orgId: org.id, adminEmail, headers, projectId: project.id, actionTypeId: actionTypes[0].id };
}

async function newActionCode(request: APIRequestContext, world: World, title: string): Promise<string> {
  const created = await request.post(`${apiBaseUrl}/api/v1/projects/${world.projectId}/actions`, {
    headers: world.headers, data: { title, action_type_id: world.actionTypeId },
  });
  expect(created.status(), await created.text()).toBe(201);
  return (await created.json()).unique_code as string;
}

test.describe("record code prefixes", () => {
  test("an organisation prefix applies to new actions, a project overrides it, and clearing returns to the inherited one", async ({ page }) => {
    test.setTimeout(90_000);
    const world = await createWorld(page.request, "prefix");
    await loginAs(page, world.adminEmail);
    expect(await newActionCode(page.request, world, "Before")).toBe("ACT-001");

    await test.step("the organisation administrator chooses TSK for actions", async () => {
      await page.goto(`/orgs/${world.orgId}/admin`);
      await selectOrgAdminGroup(page, "Projects");
      const toggle = page.getByRole("button", { name: "Record codes section" });
      if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
      await page.getByRole("textbox", { name: "Prefix for Action", exact: true }).fill("tsk");
      await page.getByRole("button", { name: "Save the prefix for Action" }).click();
      await expect(page.getByText("Record code prefix saved.")).toBeVisible();
      await expect(page.getByRole("textbox", { name: "Prefix for Action", exact: true })).toHaveValue("TSK");
    });

    await test.step("new actions use it and the number carries on", async () => {
      expect(await newActionCode(page.request, world, "After")).toBe("TSK-002");
    });

    await test.step("the project says it inherits the prefix from the organisation", async () => {
      await page.goto(`/projects/${world.projectId}/admin/overview`);
      const field = page.getByRole("textbox", { name: "Prefix for Action", exact: true });
      await expect(field).toHaveValue("");
      await expect(field).toHaveAttribute("placeholder", "TSK");
      await expect(page.getByText("Inherited from the organisation").first()).toBeVisible();
    });

    await test.step("the project manager overrides it for the project", async () => {
      await page.getByRole("textbox", { name: "Prefix for Action", exact: true }).fill("wrk");
      await page.getByRole("button", { name: "Save the prefix for Action" }).click();
      await expect(page.getByText("Record code prefix saved.")).toBeVisible();
      expect(await newActionCode(page.request, world, "Local")).toBe("WRK-003");
    });

    await test.step("clearing the project's own prefix returns to the organisation's", async () => {
      await page.getByRole("button", { name: "Use the inherited prefix for Action" }).click();
      await expect(page.getByText("Record code prefix reset.")).toBeVisible();
      await expect(page.getByRole("textbox", { name: "Prefix for Action", exact: true })).toHaveValue("");
      expect(await newActionCode(page.request, world, "Back")).toBe("TSK-004");
    });
  });

  test("a prefix another record type already uses is refused with the reason", async ({ page }) => {
    test.setTimeout(60_000);
    const world = await createWorld(page.request, "clash");
    await loginAs(page, world.adminEmail);
    await page.goto(`/projects/${world.projectId}/admin/overview`);
    await page.getByRole("textbox", { name: "Prefix for Action", exact: true }).fill("cr");
    await page.getByRole("button", { name: "Save the prefix for Action" }).click();
    await expect(page.getByText(/already the prefix of change request records/i)).toBeVisible();
    expect(await newActionCode(page.request, world, "Still default")).toBe("ACT-001");
  });
});
