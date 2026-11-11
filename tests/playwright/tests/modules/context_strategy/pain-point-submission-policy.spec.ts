import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup, selectProjectAdminGroup } from "../../e2e-workflows/helpers";

const API_BASE_URL = "http://localhost:8000";

/**
 * Creates a disposable organisation (Context & Strategy on), an organisation administrator, one project and a plain
 * project member, all through the API with unique names, so the spec depends on no shared seed data and leaves none
 * behind (`deleteOrgOnCleanup`).
 */
async function setup(page: Page, request: APIRequestContext) {
  const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
  const adminEmail = `e2e-pp-policy-admin-${suffix}@example.com`;
  const memberEmail = `e2e-pp-policy-member-${suffix}@example.com`;
  const login = await request.post(`${API_BASE_URL}/api/v1/auth/login`, {
    data: { email: "admin@example.com", password: "ChangeMe123!" },
  });
  const serverHeaders = { Authorization: `Bearer ${(await login.json()).access_token}` };
  const org = await (await request.post(`${API_BASE_URL}/api/v1/orgs`, {
    headers: serverHeaders, data: { name: `E2E Pain Point Policy ${suffix}` },
  })).json();
  deleteOrgOnCleanup({ id: org.id });
  await request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Policy Admin", password: PASSWORD, role: "org_admin" },
  });
  const member = await (await request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders, data: { email: memberEmail, display_name: "E2E Policy Member", password: PASSWORD, role: "member" },
  })).json();
  await loginAs(page, adminEmail, PASSWORD);
  const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
  const headers = { Authorization: `Bearer ${token}` };
  const enable = await request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/context_strategy`, {
    headers, data: { enabled: true, default_project_enabled: true },
  });
  expect(enable.ok()).toBeTruthy();
  const project = await (await request.post(`${API_BASE_URL}/api/v1/projects`, {
    headers, data: { organization_id: org.id, name: `Policy Project ${suffix}`, summary: "" },
  })).json();
  const role = await request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/roles`, {
    headers, data: { user_id: member.user_id, role: "member" },
  });
  expect(role.ok()).toBeTruthy();
  return { org, project, adminEmail, memberEmail };
}

/**
 * Job to be done: Pain Point submission is for Pain Point Managers by default (ordinary requests go to Enhancement
 * Requests); a project or the organisation can allow any project member, and a member sees the reason instead of a
 * New button wherever it is restricted.
 */
test.describe("Context & Strategy: Pain Point submission policy", () => {
  installCleanupHook();

  test("the default restricts members and a project allows them", async ({ page, request }) => {
    const { project, adminEmail, memberEmail } = await setup(page, request);

    await test.step("by default a member sees the reason instead of New Pain Point", async () => {
      await loginAs(page, memberEmail, PASSWORD);
      await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points`);
      await expect(page.getByRole("note")).toContainText("Pain Points are submitted by Pain Point Managers in this project.");
      await expect(page.getByRole("button", { name: "New Pain Point" })).toHaveCount(0);
    });

    await test.step("the project administrator allows any project member", async () => {
      await loginAs(page, adminEmail, PASSWORD);
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Pain Point Submission", "Pain Points");
      await expect(page.getByTestId("pain-point-submission-inherited")).toContainText(
        "Inherited from the platform default: Pain Point Managers only.",
      );
      await page.getByLabel("Who can submit a Pain Point").selectOption({ label: "Any project member" });
      await expect(page.getByText("Submission setting saved.")).toBeVisible();
      await expect(page.getByTestId("pain-point-submission-inherited")).toHaveCount(0);
    });

    await test.step("a member now sees New Pain Point", async () => {
      await loginAs(page, memberEmail, PASSWORD);
      await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points`);
      await expect(page.getByRole("button", { name: "New Pain Point" })).toBeVisible();
    });

    await test.step("the administrator submits whichever is chosen", async () => {
      await loginAs(page, adminEmail, PASSWORD);
      await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points`);
      await expect(page.getByRole("button", { name: "New Pain Point" })).toBeVisible();
    });
  });

  test("the organisation default applies to a project that has no setting of its own", async ({ page, request }) => {
    const { org, project, adminEmail, memberEmail } = await setup(page, request);

    await test.step("the organisation administrator allows any project member by default", async () => {
      await loginAs(page, adminEmail, PASSWORD);
      await page.goto(`/orgs/${org.id}/admin`);
      await selectOrgAdminGroup(page, "Pain Point Submission", "Pain Points");
      await page.getByLabel("Who can submit a Pain Point by default").selectOption({ label: "Any project member" });
      await expect(page.getByText("Submission default saved.")).toBeVisible();
    });

    await test.step("the project shows the inherited value and a member can submit", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Pain Point Submission", "Pain Points");
      await expect(page.getByTestId("pain-point-submission-inherited")).toContainText(
        "Inherited from the organisation: Any project member.",
      );
      await loginAs(page, memberEmail, PASSWORD);
      await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points`);
      await expect(page.getByRole("button", { name: "New Pain Point" })).toBeVisible();
    });

    await test.step("the project restricts it again for itself", async () => {
      await loginAs(page, adminEmail, PASSWORD);
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Pain Point Submission", "Pain Points");
      await page.getByLabel("Who can submit a Pain Point").selectOption({ label: "Pain Point Managers only" });
      await expect(page.getByText("Submission setting saved.")).toBeVisible();
      await loginAs(page, memberEmail, PASSWORD);
      await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points`);
      await expect(page.getByRole("button", { name: "New Pain Point" })).toHaveCount(0);
    });
  });
});
