import { expect, test } from "@playwright/test";

import { apiHeaders, createDisposableProject, installCleanupHook, loginAs, PASSWORD, PERSONAS } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: the owner of a component's track, who is not a project manager, moves it from the project's own "Stage
 * phases" page without needing project administration; a track they do not own cannot be moved by them.
 *
 * Uses a disposable project (archived by the cleanup hook) and a member created for the test.
 */
test.describe("stage phases page", () => {
  installCleanupHook();

  test("a track's owner moves it from the Delivery status page", async ({ page }) => {
    test.setTimeout(60_000);
    const adminEmail = PERSONAS.orgAdminAlphaBeta.email;
    const project = await createDisposableProject(page.request, adminEmail, "E2E Stage Phases Owner");
    const headers = await apiHeaders(page.request, adminEmail);
    const [first, second] = project.components;
    const stamp = Date.now();

    const ownerEmail = `e2e-track-owner-${stamp}@example.com`;
    const created = await page.request.post(`${API}/orgs/${project.organizationId}/users`, {
      headers, data: { email: ownerEmail, display_name: "E2E Track Owner", password: PASSWORD, role: "member" },
    });
    expect(created.ok()).toBeTruthy();
    const ownerId: string = (await created.json()).user_id;
    expect((await page.request.post(`${API}/projects/${project.projectId}/roles`, { headers, data: { user_id: ownerId, role: "member" } })).ok()).toBeTruthy();

    const stages: { id: string; name: string }[] = await (await page.request.get(`${API}/projects/${project.projectId}/stages`, { headers })).json();
    expect((await page.request.put(`${API}/projects/${project.projectId}/component-phases-settings`, { headers, data: { mode: "on" } })).ok()).toBeTruthy();
    const owned = await page.request.patch(
      `${API}/projects/${project.projectId}/components/${first.id}/stages/${stages[0].id}/track`,
      { headers, data: { owner: { type: "user", id: ownerId } } },
    );
    expect(owned.ok()).toBeTruthy();

    await loginAs(page, ownerEmail);
    await page.goto(`/projects/${project.projectId}/stage-phases`);
    await expect(page.getByRole("heading", { name: "Delivery status" })).toBeVisible();
    await expect(page.getByRole("combobox", { name: new RegExp(`^Phase of ${first.name} in `) }).first()).toBeEnabled();
    await expect(page.getByRole("combobox", { name: new RegExp(`^Phase of ${second.name} in `) }).first()).toBeDisabled();

    const picker = page.getByRole("combobox", { name: `Phase of ${first.name} in ${stages[0].name}` });
    await picker.selectOption({ label: "Review" });
    await expect(picker.locator("option:checked")).toHaveText("Review");
  });
});
