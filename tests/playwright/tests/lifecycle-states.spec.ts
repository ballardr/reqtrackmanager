import { expect, test } from "@playwright/test";

import {
  deleteOrgOnCleanup, expectCurrentStep, installCleanupHook, loginAs, PASSWORD, promoteTo, selectOrgAdminGroup,
  selectProjectAdminGroup,
} from "./e2e-workflows/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API_BASE_URL = "http://localhost:8000";

/**
 * Job to be done: e2e coverage of lifecycle states as configuration. A project administrator turns an optional state
 * off and a record moves past it in one Promote; the organisation requires the state, which locks the project's row;
 * an exempt project may turn it off again; an approval state (Decision Approved) stays behind its approval dialog.
 *
 * Uses a disposable org, admin and project created through the API, with Context & Strategy and Decision Management
 * enabled for the organisation.
 */
test.describe("Lifecycles: project configuration and organisation requirement", () => {
  test("a project turns Triaged off, the organisation requires it, and an exemption lifts the requirement", async ({ page }) => {
    const suffix = Date.now();
    const adminEmail = `e2e-lifecycle-admin-${suffix}@example.com`;
    const projectName = `E2E Lifecycle Project ${suffix}`;
    const painPointTitle = `Slow export ${suffix}`;
    const decisionTitle = `Use Postgres ${suffix}`;

    const serverAdminToken = (await (await page.request.post(`${API_BASE_URL}/api/v1/auth/login`, {
      data: { email: "admin@example.com", password: "ChangeMe123!" },
    })).json()).access_token;
    const serverAdminHeaders = { Authorization: `Bearer ${serverAdminToken}` };
    const org = await (await page.request.post(`${API_BASE_URL}/api/v1/orgs`, {
      headers: serverAdminHeaders, data: { name: `E2E Lifecycle Org ${suffix}` },
    })).json();
    deleteOrgOnCleanup({ id: org.id });
    await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users`, {
      headers: serverAdminHeaders,
      data: { email: adminEmail, display_name: "E2E Lifecycle Admin", password: PASSWORD, role: "org_admin" },
    });

    await loginAs(page, adminEmail, PASSWORD);
    const adminToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const headers = { Authorization: `Bearer ${adminToken}` };
    for (const key of ["context_strategy", "decisions"]) {
      const enabled = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/${key}`, { headers, data: { enabled: true } });
      expect(enabled.ok()).toBeTruthy();
    }
    const project = await (await page.request.post(`${API_BASE_URL}/api/v1/projects`, {
      headers, data: { organization_id: org.id, name: projectName, summary: "" },
    })).json();

    const types = await (await page.request.get(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/context_strategy/pain-point-types`, { headers })).json();
    const painPoint = await (await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/context_strategy/pain-points`, {
      headers,
      data: { title: painPointTitle, description: "It takes minutes.", priority: "medium", business_impact: "Delays reporting.", pain_point_type_id: types[0].id },
    })).json();
    const decisionTypes = await (await page.request.get(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/decisions/decision-types`, { headers })).json();
    const decision = await (await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/decisions`, {
      headers, data: { title: decisionTitle, decision_statement: "We will use PostgreSQL.", decision_type_id: decisionTypes[0].id },
    })).json();

    await test.step("a project administrator turns Triaged off, so Submitted promotes straight to Accepted", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Lifecycles");
      const triaged = page.getByRole("checkbox", { name: "Use Triaged" });
      await expect(triaged).toBeChecked();
      await triaged.click();
      await expect(page.getByText("The lifecycle settings were saved.")).toBeVisible();
      await expect(triaged).not.toBeChecked();

      await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points/${painPoint.id}`);
      await expect(page.getByRole("button", { name: "Next step: Accepted" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Next step: Triaged" })).toHaveCount(0);
      await promoteTo(page, "Accepted");
      await page.getByRole("dialog", { name: "Accept this Pain Point?" }).getByRole("button", { name: "Accept" }).click();
      await expectCurrentStep(page, "Accepted");
    });

    await test.step("a Decision with both review steps off still needs the approval dialog", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Lifecycles");
      // Several types share these state names, so the row of the Decision type is addressed by its region.
      const row = page.getByRole("region", { name: "Decision", exact: true });
      await row.getByRole("checkbox", { name: "Use Proposed" }).click();
      await expect(row.getByRole("checkbox", { name: "Use Proposed" })).not.toBeChecked();
      await row.getByRole("checkbox", { name: "Use Under review" }).click();
      await expect(row.getByRole("checkbox", { name: "Use Under review" })).not.toBeChecked();

      await page.goto(`/projects/${project.id}/modules/decisions/${decision.id}`);
      await promoteTo(page, "Approved");
      await page.getByRole("dialog", { name: "Approve this Decision?" }).getByRole("button", { name: "Approve" }).click();
      await expectCurrentStep(page, "Approved");
    });

    await test.step("the organisation requires Triaged, which locks the project's row", async () => {
      await page.goto(`/orgs/${org.id}/admin`);
      await selectOrgAdminGroup(page, "Lifecycles");
      await page.getByRole("checkbox", { name: "Require Triaged" }).click();
      await expect(page.getByRole("checkbox", { name: "Require Triaged" })).toBeChecked();

      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Lifecycles");
      const triaged = page.getByRole("checkbox", { name: "Use Triaged" });
      await expect(triaged).toBeChecked();
      await expect(triaged).toBeDisabled();
      await expect(page.getByText("Required by the organisation")).toBeVisible();
    });

    await test.step("an exempt project may turn the required state off again", async () => {
      await page.goto(`/orgs/${org.id}/admin`);
      await selectOrgAdminGroup(page, "Lifecycles");
      const section = page.getByRole("region", { name: "Pain Point" });
      await section.getByRole("button", { name: "Exempt a project" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByRole("combobox", { name: /Project/ }).selectOption({ label: `${project.code} ${projectName}` });
      await dialog.getByRole("button", { name: "Exempt a project" }).click();
      await expect(section.getByText(projectName, { exact: false })).toBeVisible();

      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Lifecycles");
      await expect(page.getByText("Exempt from the organisation's requirement")).toBeVisible();
      await expect(page.getByRole("checkbox", { name: "Use Triaged" })).toBeEnabled();
    });
  });
});
