import { expect, test } from "@playwright/test";

import {
  approveRequirementFromDetail, deleteOrgOnCleanup, expectNoPromote, installCleanupHook, loginAs, PASSWORD,
  selectOrgAdminGroup, selectProjectAdminGroup,
} from "./e2e-workflows/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API_BASE_URL = "http://localhost:8000";

/**
 * Job to be done: e2e coverage of approval separation. By default the person who created a requirement may approve it
 * and the record is marked Self-approved; a project can require a separate approver, which the server enforces; the
 * organisation can require one for every project, which locks the project's choice until the project is exempt, and a
 * deliberate self-approval in an exempt project needs a comment.
 *
 * Uses a disposable org, admin and project created through the API.
 */
test.describe("Approval separation", () => {
  test("a creator self-approves by default, a project and the organisation can require a separate approver", async ({ page }) => {
    const suffix = Date.now();
    const adminEmail = `e2e-approval-admin-${suffix}@example.com`;
    const projectName = `E2E Approval Project ${suffix}`;

    const serverAdminToken = (await (await page.request.post(`${API_BASE_URL}/api/v1/auth/login`, {
      data: { email: "admin@example.com", password: "ChangeMe123!" },
    })).json()).access_token;
    const serverAdminHeaders = { Authorization: `Bearer ${serverAdminToken}` };
    const org = await (await page.request.post(`${API_BASE_URL}/api/v1/orgs`, {
      headers: serverAdminHeaders, data: { name: `E2E Approval Org ${suffix}` },
    })).json();
    deleteOrgOnCleanup({ id: org.id });
    await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users`, {
      headers: serverAdminHeaders,
      data: { email: adminEmail, display_name: "E2E Approval Admin", password: PASSWORD, role: "org_admin" },
    });

    await loginAs(page, adminEmail, PASSWORD);
    const adminToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const headers = { Authorization: `Bearer ${adminToken}` };
    const project = await (await page.request.post(`${API_BASE_URL}/api/v1/projects`, {
      headers, data: { organization_id: org.id, name: projectName, summary: "" },
    })).json();
    const component = await (await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/components`, {
      headers, data: { name: "Software", prefix: "SW" },
    })).json();
    const category = await (await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/categories`, {
      headers, data: { name: "Performance", prefix: "PERF", component_id: component.id },
    })).json();
    const createRequirement = async (name: string) => (await (await page.request.post(
      `${API_BASE_URL}/api/v1/projects/${project.id}/requirements`, {
        headers, data: { name, component_id: component.id, category_id: category.id },
      },
    )).json());
    const first = await createRequirement(`Boot within 30 seconds ${suffix}`);
    const second = await createRequirement(`Respond within 30 ms ${suffix}`);
    const third = await createRequirement(`Export within a minute ${suffix}`);
    const approve = (id: string, comment?: string) => page.request.post(
      `${API_BASE_URL}/api/v1/projects/${project.id}/requirements/${id}/approve`, { headers, data: comment ? { comment } : {} },
    );

    await test.step("by default the creator approves their own requirement and the record is marked", async () => {
      await page.goto(`/projects/${project.id}/requirements/${first.id}`);
      await expect(page.getByText("Self-approved")).toHaveCount(0);
      await approveRequirementFromDetail(page);
      await expect(page.getByText("Self-approved")).toBeVisible();
    });

    await test.step("a project administrator requires a separate approver, and the server refuses the creator", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Lifecycles");
      const section = page.getByRole("region", { name: "Approval" });
      await section.getByRole("combobox", { name: "Requirement approval" }).selectOption({ label: "Separate approver required" });
      await expect(page.getByText("The approval settings were saved.")).toBeVisible();

      await page.goto(`/projects/${project.id}/requirements/${second.id}`);
      await expectNoPromote(page, "Approved");
      const refused = await approve(second.id, "Looks right.");
      expect(refused.status()).toBe(403);
      expect((await refused.json()).detail).toContain("different person");
    });

    await test.step("the organisation requires a separate approver, which locks the project's choice", async () => {
      await page.goto(`/orgs/${org.id}/admin`);
      await selectOrgAdminGroup(page, "Lifecycles");
      const orgSection = page.getByRole("region", { name: "Approval" });
      await orgSection.getByRole("combobox", { name: "Requirement approval" }).selectOption({ label: "Required for every project" });
      await expect(page.getByText("The approval settings were saved.")).toBeVisible();

      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Lifecycles");
      const section = page.getByRole("region", { name: "Approval" });
      await expect(section.getByRole("combobox", { name: "Requirement approval" })).toBeDisabled();
      await expect(section.getByText("Required by the organisation")).toBeVisible();
    });

    await test.step("an exempt project may let its creator approve, with a comment, and the record is marked", async () => {
      await page.goto(`/orgs/${org.id}/admin`);
      await selectOrgAdminGroup(page, "Lifecycles");
      const orgGroup = page.getByRole("group", { name: "Requirement approval" });
      await orgGroup.getByRole("button", { name: "Exempt a project" }).click();
      const dialog = page.getByRole("dialog", { name: "Exempt a project from the Requirement approval requirement" });
      await dialog.getByRole("combobox", { name: /Project/ }).selectOption({ label: `${project.code} ${projectName}` });
      await dialog.getByRole("button", { name: "Exempt a project" }).click();
      await expect(orgGroup.getByText(projectName, { exact: false })).toBeVisible();

      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Lifecycles");
      const section = page.getByRole("region", { name: "Approval" });
      await expect(section.getByText("Exempt from the organisation's requirement")).toBeVisible();
      const choice = section.getByRole("combobox", { name: "Requirement approval" });
      await expect(choice).toBeEnabled();
      await choice.selectOption({ label: "Submitter may approve, with a comment" });
      await expect(page.getByText("The approval settings were saved.")).toBeVisible();

      const missing = await approve(third.id);
      expect(missing.status()).toBe(400);
      expect((await missing.json()).detail).toContain("comment is required");
      await page.goto(`/projects/${project.id}/requirements/${third.id}`);
      await approveRequirementFromDetail(page, "Solo project: checked against the test report.");
      await expect(page.getByText("Self-approved")).toBeVisible();
    });
  });
});
