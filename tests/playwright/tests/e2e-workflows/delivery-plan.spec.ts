import { expect, test } from "@playwright/test";

import { apiHeaders, createDisposableProject, installCleanupHook, loginAs, PASSWORD, PERSONAS } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: anyone who can see a project opens its Delivery status page and sees, for each stage and each component's
 * track, how far along it is, when it is expected to finish and whether it is overdue, as a table or a timeline; a project
 * manager moves a stage and sets its dates there, a track's owner (not a manager) only moves their own track.
 *
 * Uses a disposable project (archived by the cleanup hook) and a member created for the test.
 */
test.describe("delivery plan page", () => {
  installCleanupHook();

  test("progress, dates and overdue read in both views, and a manager schedules in place", async ({ page }) => {
    test.setTimeout(90_000);
    const adminEmail = PERSONAS.orgAdminAlphaBeta.email;
    const project = await createDisposableProject(page.request, adminEmail, "E2E Delivery Plan");
    const headers = await apiHeaders(page.request, adminEmail);
    const [first] = project.components;
    const stages: { id: string; name: string; phase_id: string }[] =
      await (await page.request.get(`${API}/projects/${project.projectId}/stages`, { headers })).json();
    const workflowPhases: { id: string; name: string }[] = (await (await page.request.get(
      `${API}/projects/${project.projectId}/stage-workflows`, { headers })).json())[0].phases;
    expect((await page.request.put(`${API}/projects/${project.projectId}/component-phases-settings`, { headers, data: { mode: "on" } })).ok()).toBeTruthy();

    // A range that ended long ago on the stage's current phase makes the stage overdue.
    const planned = await page.request.put(`${API}/projects/${project.projectId}/stages/${stages[0].id}/phase-plan`, {
      headers, data: { phase_id: stages[0].phase_id, expected_from: "2020-01-01", expected_to: "2020-02-01" },
    });
    expect(planned.ok()).toBeTruthy();
    expect(workflowPhases.length).toBeGreaterThan(1);

    await loginAs(page, adminEmail);
    await page.goto(`/projects/${project.projectId}/stage-phases`);

    await test.step("the page is in the navigation because the project has stages, titled Project stages", async () => {
      await expect(page.getByRole("link", { name: "Delivery status" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Project stages" })).toBeVisible();
    });

    await test.step("the table shows progress, the expected range and an overdue badge", async () => {
      // The chosen view is kept per person, so a repeated run opens on the last one used.
      await page.getByRole("button", { name: "Table view" }).click();
      const stageTable = page.getByRole("table", { name: "Status by stage" });
      await expect(stageTable.getByRole("columnheader", { name: "Progress" })).toBeVisible();
      await expect(stageTable.getByRole("columnheader", { name: "Expected" })).toBeVisible();
      await expect(stageTable.getByText("Overdue", { exact: true })).toBeVisible();
      await expect(stageTable.getByText(/^Step 1 of \d+$/).first()).toBeVisible();
    });

    await test.step("the timeline draws the same rows and the choice is kept on reload", async () => {
      await page.getByRole("button", { name: "Timeline view" }).click();
      await expect(page.getByRole("list", { name: "Delivery timeline" }).first()).toBeVisible();
      await expect(page.getByRole("list", { name: "Delivery timeline" }).first().getByText("Overdue", { exact: true })).toBeVisible();
      await page.waitForLoadState("networkidle");
      await page.reload();
      await expect(page.getByRole("list", { name: "Delivery timeline" }).first()).toBeVisible();
      await page.getByRole("button", { name: "Table view" }).click();
      await expect(page.getByRole("table", { name: "Status by stage" })).toBeVisible();
    });

    await test.step("a manager sets a track's dates in place", async () => {
      await page.getByRole("button", { name: `Set expected dates for ${first.name} in ${stages[0].name}` }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByLabel("Expected start").fill("2099-01-01");
      await dialog.getByLabel("Expected end").fill("2099-02-01");
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(page.getByRole("dialog")).toHaveCount(0);
      await expect(page.getByRole("table", { name: /Status by component and stage/ }).getByText(/2099/).first()).toBeVisible();
    });

    await test.step("a manager moves a stage from the page", async () => {
      const picker = page.getByRole("combobox", { name: `Phase of ${stages[0].name}` });
      await picker.selectOption({ label: workflowPhases[1].name });
      await expect(picker.locator("option:checked")).toHaveText(workflowPhases[1].name);
    });
  });

  test("a track's owner who is not a manager cannot schedule or move a stage", async ({ page }) => {
    test.setTimeout(90_000);
    const adminEmail = PERSONAS.orgAdminAlphaBeta.email;
    const project = await createDisposableProject(page.request, adminEmail, "E2E Delivery Plan Member");
    const headers = await apiHeaders(page.request, adminEmail);
    const [first] = project.components;
    const stamp = Date.now();
    const memberEmail = `e2e-delivery-member-${stamp}@example.com`;
    const created = await page.request.post(`${API}/orgs/${project.organizationId}/users`, {
      headers, data: { email: memberEmail, display_name: "E2E Delivery Member", password: PASSWORD, role: "member" },
    });
    expect(created.ok()).toBeTruthy();
    const memberId: string = (await created.json()).user_id;
    expect((await page.request.post(`${API}/projects/${project.projectId}/roles`, { headers, data: { user_id: memberId, role: "member" } })).ok()).toBeTruthy();
    const stages: { id: string; name: string }[] = await (await page.request.get(`${API}/projects/${project.projectId}/stages`, { headers })).json();
    expect((await page.request.put(`${API}/projects/${project.projectId}/component-phases-settings`, { headers, data: { mode: "on" } })).ok()).toBeTruthy();
    expect((await page.request.patch(
      `${API}/projects/${project.projectId}/components/${first.id}/stages/${stages[0].id}/track`,
      { headers, data: { owner: { type: "user", id: memberId } } },
    )).ok()).toBeTruthy();

    await loginAs(page, memberEmail);
    await page.goto(`/projects/${project.projectId}/stage-phases`);
    await expect(page.getByRole("combobox", { name: `Phase of ${stages[0].name}` })).toBeDisabled();
    await expect(page.getByRole("button", { name: /Set expected dates for/ })).toHaveCount(0);
    await expect(page.getByRole("combobox", { name: `Phase of ${first.name} in ${stages[0].name}` })).toBeEnabled();
  });
});
