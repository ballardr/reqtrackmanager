import { expect, type APIRequestContext, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD } from "./helpers";

// Deletes this file's disposable org after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a stakeholder or project administrator traces a requirement while it is still being
 * worked on, but cannot change the links of an approved requirement directly; only someone holding the
 * Link permission can (the permission exists to link in every state), and everyone else proposes the
 * change in a change request.
 *
 * Covers: a stakeholder sees "Add link" on a draft requirement and links it; on an approved requirement
 * the page shows no add or remove control for them; a user holding the Link permission still sees it
 * on the approved one.
 *
 * Builds its own organisation, so it depends on no shared fixture or earlier run.
 */

const apiBaseUrl = "http://localhost:8000";

async function setup(request: APIRequestContext) {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  const serverToken = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: "admin@example.com", password: "ChangeMe123!" } })).json()
  ).access_token;
  const serverHeaders = { Authorization: `Bearer ${serverToken}` };
  const org = await (await request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: serverHeaders, data: { name: `E2E Link Roles ${suffix}` } })).json();
  deleteOrgOnCleanup({ id: org.id });
  const adminEmail = `e2e-linkroles-admin-${suffix}@example.com`;
  await request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Admin", password: PASSWORD, role: "org_admin" },
  });
  const adminToken = (await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: adminEmail, password: PASSWORD } })).json()).access_token;
  const headers = { Authorization: `Bearer ${adminToken}` };
  const project = await (
    await request.post(`${apiBaseUrl}/api/v1/projects`, { headers, data: { organization_id: org.id, name: `E2E Link Roles Project ${suffix}`, summary: "" } })
  ).json();
  const component = await (await request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/components`, { headers, data: { name: "Software", prefix: "SW" } })).json();
  const category = await (
    await request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/categories`, { headers, data: { name: "Functional", prefix: "FN", component_id: component.id } })
  ).json();
  const requirement = async (name: string, approve = false): Promise<string> => {
    const created = await (
      await request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/requirements`, {
        headers, data: { name, reasoning: "e2e", component_id: component.id, category_id: category.id, keywords: [] },
      })
    ).json();
    if (approve) await request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/requirements/${created.id}/approve`, { headers });
    return created.id;
  };
  const user = async (label: string, projectRole: string): Promise<string> => {
    const email = `e2e-linkroles-${label}-${suffix}@example.com`;
    const created = await (
      await request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
        headers, data: { email, display_name: `E2E ${label}`, password: PASSWORD, role: "member" },
      })
    ).json();
    await request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/roles`, { headers, data: { user_id: created.user_id, role: projectRole } });
    return email;
  };
  return { orgId: org.id as string, projectId: project.id as string, headers, requirement, user };
}

test.describe("linking by default role", () => {
  test("a stakeholder links a draft requirement but has no link controls on an approved one", async ({ page }) => {
    const world = await setup(page.request);
    const draft = await world.requirement("Draft requirement");
    await world.requirement("Another draft requirement");
    const approved = await world.requirement("Approved requirement", true);
    const email = await world.user("stakeholder", "stakeholder");
    await loginAs(page, email, PASSWORD);

    await test.step("the draft requirement can be linked", async () => {
      await page.goto(`/projects/${world.projectId}/requirements/${draft}`);
      const links = page.getByRole("region", { name: "Links", exact: true });
      await links.getByRole("button", { name: "Add link" }).click();
      const dialog = page.getByRole("dialog", { name: "Add a link" });
      await dialog.getByLabel("Link to").selectOption({ label: "Requirement" });
      const option = dialog.getByRole("option", { name: /Another draft requirement/ });
      await expect(option).toHaveCount(1);
      await dialog.getByLabel("Record").selectOption((await option.getAttribute("value")) as string);
      await dialog.getByRole("button", { name: "Add link" }).click();
      await expect(page.getByText("Link added.")).toBeVisible();
      await expect(links.getByText(/Another draft requirement/)).toBeVisible();
    });

    await test.step("the approved requirement offers no way to link it directly", async () => {
      await page.goto(`/projects/${world.projectId}/requirements/${approved}`);
      const links = page.getByRole("region", { name: "Links", exact: true });
      await expect(links).toBeVisible();
      await expect(links.getByRole("button", { name: "Add link" })).toHaveCount(0);
    });
  });

  test("someone holding the Link permission can still link an approved requirement", async ({ page }) => {
    const world = await setup(page.request);
    const approved = await world.requirement("Approved requirement", true);
    await world.requirement("Other requirement");
    const email = await world.user("linker", "member");
    const users: { user_id: string; email: string }[] = await (
      await page.request.get(`${apiBaseUrl}/api/v1/orgs/${world.orgId}/users`, { headers: world.headers })
    ).json();
    const userId = users.find((u) => u.email === email)!.user_id;
    const role = await (
      await page.request.post(`${apiBaseUrl}/api/v1/orgs/${world.orgId}/custom-roles`, {
        headers: world.headers, data: { name: "Linker", description: "", scope: "project", permissions: ["requirement:link:"] },
      })
    ).json();
    const granted = await page.request.post(`${apiBaseUrl}/api/v1/orgs/${world.orgId}/custom-roles/${role.id}/users/${userId}`, {
      headers: world.headers, data: { project_id: world.projectId },
    });
    expect(granted.status()).toBe(204);

    await loginAs(page, email, PASSWORD);
    await page.goto(`/projects/${world.projectId}/requirements/${approved}`);
    await expect(page.getByRole("region", { name: "Links", exact: true }).getByRole("button", { name: "Add link" })).toBeVisible();
  });
});
