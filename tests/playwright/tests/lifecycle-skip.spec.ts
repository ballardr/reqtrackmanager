import { expect, test } from "@playwright/test";

import {
  chooseRecordMenuAction, deleteOrgOnCleanup, expectCurrentStep, installCleanupHook, loginAs, PASSWORD, recordActionNames,
  selectOrgAdminGroup, selectProjectAdminGroup,
} from "./e2e-workflows/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API_BASE_URL = "http://localhost:8000";

/**
 * Job to be done: e2e coverage of skipping steps on one record. Skipping is off until a project administrator allows
 * it; a person then moves a Pain Point from Submitted to Addressed with a reason, and the history names the skipped
 * steps; the organisation forbids skipping, which locks the project's switch and refuses the move, and an exemption
 * lifts the ban again.
 *
 * Uses a disposable org, admin and project created through the API, with Context & Strategy enabled.
 */
test.describe("Lifecycles: skipping steps on one record", () => {
  test("a project allows skipping, a record skips two steps, and the organisation can forbid it", async ({ page }) => {
    const suffix = Date.now();
    const adminEmail = `e2e-skip-admin-${suffix}@example.com`;
    const projectName = `E2E Skip Project ${suffix}`;

    const serverAdminToken = (await (await page.request.post(`${API_BASE_URL}/api/v1/auth/login`, {
      data: { email: "admin@example.com", password: "ChangeMe123!" },
    })).json()).access_token;
    const serverAdminHeaders = { Authorization: `Bearer ${serverAdminToken}` };
    const org = await (await page.request.post(`${API_BASE_URL}/api/v1/orgs`, {
      headers: serverAdminHeaders, data: { name: `E2E Skip Org ${suffix}` },
    })).json();
    deleteOrgOnCleanup({ id: org.id });
    await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users`, {
      headers: serverAdminHeaders,
      data: { email: adminEmail, display_name: "E2E Skip Admin", password: PASSWORD, role: "org_admin" },
    });

    await loginAs(page, adminEmail, PASSWORD);
    const adminToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const headers = { Authorization: `Bearer ${adminToken}` };
    const enabled = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/context_strategy`, { headers, data: { enabled: true } });
    expect(enabled.ok()).toBeTruthy();
    const project = await (await page.request.post(`${API_BASE_URL}/api/v1/projects`, {
      headers, data: { organization_id: org.id, name: projectName, summary: "" },
    })).json();
    const types = await (await page.request.get(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/context_strategy/pain-point-types`, { headers })).json();
    const createPainPoint = async (title: string) => (await (await page.request.post(
      `${API_BASE_URL}/api/v1/projects/${project.id}/modules/context_strategy/pain-points`, {
        headers,
        data: { title, description: "It takes minutes.", priority: "medium", business_impact: "Delays reporting.", pain_point_type_id: types[0].id },
      },
    )).json());
    const first = await createPainPoint(`Slow export ${suffix}`);
    const second = await createPainPoint(`Slow import ${suffix}`);

    await test.step("skipping steps is not offered while the project has not allowed it", async () => {
      await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points/${first.id}`);
      await expect(page.getByRole("button", { name: "Next step: Triaged" })).toBeVisible();
      expect(await recordActionNames(page, "Pain Point")).not.toContain("Skip steps…");
    });

    await test.step("a project administrator allows skipping steps", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Lifecycles");
      const allow = page.getByRole("checkbox", { name: "Allow skipping steps" });
      await expect(allow).not.toBeChecked();
      await allow.click();
      await expect(page.getByText("The lifecycle settings were saved.")).toBeVisible();
      await expect(allow).toBeChecked();
    });

    await test.step("a record skips Triaged and Accepted with a reason, and the history names them", async () => {
      await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points/${first.id}`);
      await chooseRecordMenuAction(page, "Skip steps…");
      const dialog = page.getByRole("dialog", { name: "Skip steps of this Pain Point" });
      await dialog.getByRole("combobox", { name: /Move to/ }).selectOption({ label: "Addressed (skips Triaged, Accepted)" });
      const save = dialog.getByRole("button", { name: "Skip steps" });
      await expect(save).toBeDisabled();
      await dialog.getByLabel(/Reason/).fill("Fixed in the hot patch");
      await save.click();
      await expectCurrentStep(page, "Addressed");

      await page.goto(`/projects/${project.id}/history`);
      await expect(page.getByText("skipped the steps Triaged, Accepted").first()).toBeVisible();
      await expect(page.getByText("Fixed in the hot patch").first()).toBeVisible();
    });

    await test.step("the organisation forbids skipping, which locks the project's switch and refuses the move", async () => {
      await page.goto(`/orgs/${org.id}/admin`);
      await selectOrgAdminGroup(page, "Lifecycles");
      const ban = page.getByRole("checkbox", { name: "Do not allow skipping steps" });
      await ban.click();
      await expect(ban).toBeChecked();

      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Lifecycles");
      await expect(page.getByRole("checkbox", { name: "Allow skipping steps" })).toBeDisabled();
      await expect(page.getByText("Not allowed by the organisation")).toBeVisible();

      await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points/${second.id}`);
      await expect(page.getByRole("button", { name: "Next step: Triaged" })).toBeVisible();
      expect(await recordActionNames(page, "Pain Point")).not.toContain("Skip steps…");
    });

    await test.step("an exempt project may skip steps again", async () => {
      await page.goto(`/orgs/${org.id}/admin`);
      await selectOrgAdminGroup(page, "Lifecycles");
      const section = page.getByRole("region", { name: "Skipping steps" });
      await section.getByRole("button", { name: "Exempt a project" }).click();
      const dialog = page.getByRole("dialog", { name: "Exempt a project from the ban on skipping steps" });
      await dialog.getByRole("combobox", { name: /Project/ }).selectOption({ label: `${project.code} ${projectName}` });
      await dialog.getByRole("button", { name: "Exempt a project" }).click();
      await expect(section.getByText(projectName, { exact: false })).toBeVisible();

      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Lifecycles");
      await expect(page.getByText("Exempt from the organisation's ban on skipping steps")).toBeVisible();
      await expect(page.getByRole("checkbox", { name: "Allow skipping steps" })).toBeEnabled();

      await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points/${second.id}`);
      await chooseRecordMenuAction(page, "Skip steps…");
      const skip = page.getByRole("dialog", { name: "Skip steps of this Pain Point" });
      await skip.getByRole("combobox", { name: /Move to/ }).selectOption({ label: "Accepted (skips Triaged)" });
      await skip.getByLabel(/Reason/).fill("Urgent customer request");
      await skip.getByRole("button", { name: "Skip steps" }).click();
      await expectCurrentStep(page, "Accepted");
    });
  });
});
