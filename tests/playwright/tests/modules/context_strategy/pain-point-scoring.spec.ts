import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { PASSWORD, loginAs, selectOrgAdminGroup, selectProjectAdminGroup } from "../../e2e-workflows/helpers";

const API_BASE_URL = "http://localhost:8000";

/** `DefinitionList` values render as `<input value>`s, not text nodes. */
function inputWithValue(page: Page, value: string) {
  return page.locator(`input.input[value="${value}"]:not([placeholder])`);
}

/** The `<section>` headed by `heading` (scoring editor sections). */
function section(page: Page, heading: string) {
  return page.locator("section", { has: page.getByRole("heading", { name: heading, exact: true }) });
}

/**
 * Creates a disposable org (with Context & Strategy enabled, default-on for
 * projects), an org admin, and a parent + child project — all via the API,
 * `Date.now()`-suffixed, so the spec never depends on or mutates shared
 * seed data (CLAUDE.md's test-independence rule).
 */
async function setup(page: Page, request: APIRequestContext) {
  const suffix = Date.now();
  const adminEmail = `e2e-pp-scoring-${suffix}@example.com`;
  const login = await request.post(`${API_BASE_URL}/api/v1/auth/login`, {
    data: { email: "admin@example.com", password: "ChangeMe123!" },
  });
  const serverHeaders = { Authorization: `Bearer ${(await login.json()).access_token}` };
  const org = await (await request.post(`${API_BASE_URL}/api/v1/orgs`, {
    headers: serverHeaders, data: { name: `E2E Pain Point Scoring ${suffix}` },
  })).json();
  await request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders,
    data: { email: adminEmail, display_name: "E2E Scoring Admin", password: PASSWORD, role: "org_admin" },
  });
  await loginAs(page, adminEmail, PASSWORD);
  const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
  const headers = { Authorization: `Bearer ${token}` };
  const enable = await request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/context_strategy`, {
    headers, data: { enabled: true, default_project_enabled: true },
  });
  expect(enable.ok()).toBeTruthy();
  const parent = await (await request.post(`${API_BASE_URL}/api/v1/projects`, {
    headers, data: { organization_id: org.id, name: `Scoring Parent ${suffix}`, summary: "", can_be_parent: true },
  })).json();
  const child = await (await request.post(`${API_BASE_URL}/api/v1/projects`, {
    headers, data: { organization_id: org.id, name: `Scoring Child ${suffix}`, summary: "", parent_project_id: parent.id },
  })).json();
  return { org, parent, child };
}

/**
 * Job to be done: docs/plans/module-01-context-and-strategy-plan.md Phase 10
 * — the generic scoring-matrix core, as Context & Strategy's "Pain Point
 * Scoring" admin sections expose it: org admins edit levels, the default
 * model and rating bands; projects inherit them (nearest ancestor → org →
 * module default) and can override and reset the model and bands.
 */
test.describe("Context & Strategy: Pain Point scoring configuration", () => {
  test("org admin edits levels, default model and bands; projects inherit and override", async ({ page, request }) => {
    const { org, parent, child } = await setup(page, request);

    await test.step("org: seeded levels, add a level, set the default model and bands", async () => {
      await page.goto(`/orgs/${org.id}/admin`);
      await selectOrgAdminGroup(page, "Pain Point Scoring");
      await expect(inputWithValue(page, "Blocker")).toBeVisible();
      await expect(inputWithValue(page, "Constant")).toBeVisible();

      await page.getByRole("textbox", { name: "Severity level name" }).last().fill("Catastrophic");
      await page.getByRole("spinbutton", { name: "Severity level weight" }).last().fill("6");
      await page.getByRole("button", { name: "Add Severity level" }).click();
      await expect(page.getByText("Level added.")).toBeVisible();
      await expect(inputWithValue(page, "Catastrophic")).toBeVisible();

      const defaultModel = section(page, "Default model");
      await defaultModel.getByRole("combobox", { name: "Default model" }).selectOption({ label: "Severity × Frequency" });
      await expect(page.getByText("Default model saved.")).toBeVisible();
      await expect(defaultModel.getByRole("button", { name: "Reset to module default" })).toBeVisible();

      const bands = section(page, "Rating bands");
      await bands.getByRole("combobox", { name: "Model" }).selectOption({ label: "Severity × Frequency" });
      await bands.getByRole("textbox", { name: "Band 4 label" }).fill("Severe");
      await bands.getByRole("button", { name: "Save bands" }).click();
      await expect(page.getByText("Rating bands saved.")).toBeVisible();
      await expect(bands.getByRole("cell", { name: /Severity Catastrophic, Frequency Constant: Severe/ })).toBeVisible();
    });

    await test.step("child project inherits from the org, then from its parent's override", async () => {
      await page.goto(`/projects/${child.id}/admin`);
      await selectProjectAdminGroup(page, "Pain Point Scoring");
      const defaultModel = section(page, "Default model");
      await expect(defaultModel.getByRole("combobox", { name: "Default model" })).toHaveValue("sxf");
      await expect(defaultModel.getByText("Inherited from organisation")).toBeVisible();
      await expect(section(page, "Levels").getByText(/Catastrophic \(6\)/)).toBeVisible();

      const parentOverride = await request.put(
        `${API_BASE_URL}/api/v1/projects/${parent.id}/scoring-schemes/pain_point/default-model`,
        {
          headers: { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem("reqtrack_token"))}` },
          data: { model: "sxfxc" },
        },
      );
      expect(parentOverride.ok()).toBeTruthy();
      await page.reload();
      await expect(section(page, "Default model").getByText("Inherited from parent project")).toBeVisible();
      await expect(section(page, "Default model").getByRole("combobox", { name: "Default model" })).toHaveValue("sxfxc");
    });

    await test.step("child project overrides and resets its model and bands", async () => {
      const defaultModel = section(page, "Default model");
      await defaultModel.getByRole("combobox", { name: "Default model" }).selectOption({ label: "Severity × Confidence" });
      await expect(page.getByText("Default model saved.")).toBeVisible();
      await defaultModel.getByRole("button", { name: "Use inherited value" }).click();
      await expect(defaultModel.getByText("Inherited from parent project")).toBeVisible();

      const bands = section(page, "Rating bands");
      await bands.getByRole("combobox", { name: "Model" }).selectOption({ label: "Severity × Frequency" });
      await expect(bands.getByText("Inherited from organisation")).toBeVisible();
      await bands.getByRole("textbox", { name: "Band 1 label" }).fill("Minimal");
      await bands.getByRole("button", { name: "Save bands" }).click();
      await expect(page.getByText("Rating bands saved.")).toBeVisible();
      await bands.getByRole("button", { name: "Use inherited value" }).click();
      await expect(page.getByText("Rating bands reset.")).toBeVisible();
      await expect(bands.getByText("Inherited from organisation")).toBeVisible();
    });
  });
});
