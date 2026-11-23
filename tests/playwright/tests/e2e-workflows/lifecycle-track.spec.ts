import { expect, test } from "@playwright/test";

import {
  createDisposableProject, expectCanPromote, expectCurrentStep, expectNoPromote, expectRecordLocked, installCleanupHook, loginAs,
  promoteTo, PERSONAS,
} from "./helpers";

// Archives this file's disposable projects after each test (see createDisposableProject).
installCleanupHook();

/**
 * Job to be done: see where a record is in its life and move it to the next step.
 *
 * Covers: a requirement's lifecycle track spans the header; the next step opens a Promote popover whose button runs the
 * approval dialog; the approved step carries a padlock; Promote is also the first row of the actions menu; a stakeholder,
 * who may not approve, sees a padlock on the next step and no control; at a narrow window the track collapses to the
 * current step and its position.
 */
const API = "http://localhost:8000/api/v1";

test.describe("lifecycle track", () => {
  test("a project manager promotes a requirement to Approved and a stakeholder cannot", async ({ page }) => {
    const email = PERSONAS.orgAdminAlphaBeta.email;
    const project = await createDisposableProject(page.request, email, "E2E Lifecycle");
    const created = await page.request.post(`${API}/projects/${project.projectId}/requirements`, {
      headers: project.headers,
      data: { name: `E2E Lifecycle ${Date.now()}`, component_id: project.components[0].id, category_id: project.categories[0].id },
    });
    const requirementId: string = (await created.json()).id;
    const url = `/projects/${project.projectId}/requirements/${requirementId}`;

    await test.step("the track spans the header and starts at Draft", async () => {
      await loginAs(page, email);
      await page.goto(url);
      await expectCurrentStep(page, "Draft");
      const widths = await page.locator("header.record-header").evaluate((header) => ({
        header: header.getBoundingClientRect().right,
        track: header.querySelector(".lifecycle-track__steps")!.getBoundingClientRect().right,
      }));
      expect(Math.abs(widths.header - widths.track)).toBeLessThanOrEqual(1);
      await expectCanPromote(page, "Approved");
    });

    await test.step("Promote is also the first row of the actions menu", async () => {
      await page.locator("header.record-header").getByRole("button", { name: /actions$/ }).click();
      await expect(page.getByRole("menu").getByRole("menuitem").first()).toHaveText("Promote to Approved");
      await page.keyboard.press("Escape");
    });

    await test.step("promoting through the next step opens the approval dialog and locks the requirement", async () => {
      await promoteTo(page, "Approved");
      await page.getByRole("dialog", { name: "Approve this requirement?" }).getByRole("button", { name: "Approve", exact: true }).click();
      await expectCurrentStep(page, "Approved");
      await expectRecordLocked(page);
    });

    await test.step("at a narrow window the track collapses to the current step and its position", async () => {
      await page.setViewportSize({ width: 380, height: 800 });
      await expect(page.getByRole("button", { name: /^Step 3 of 4/ })).toBeVisible();
      await page.setViewportSize({ width: 1280, height: 800 });
    });
  });

  test("a stakeholder sees a padlock on the next step and no control", async ({ page }) => {
    const project = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E Lifecycle Denied");
    const created = await page.request.post(`${API}/projects/${project.projectId}/requirements`, {
      headers: project.headers,
      data: { name: `E2E Lifecycle denied ${Date.now()}`, component_id: project.components[0].id, category_id: project.categories[0].id },
    });
    const requirementId: string = (await created.json()).id;
    const users: { user_id: string; email: string }[] = await (
      await page.request.get(`${API}/orgs/${project.organizationId}/users`, { headers: project.headers })
    ).json();
    const stakeholder = users.find((u) => u.email === PERSONAS.stakeholderAlpha.email)!;
    await page.request.post(`${API}/projects/${project.projectId}/roles`, {
      headers: project.headers, data: { user_id: stakeholder.user_id, role: "stakeholder" },
    });

    await loginAs(page, PERSONAS.stakeholderAlpha.email);
    await page.goto(`/projects/${project.projectId}/requirements/${requirementId}`);
    await expectCurrentStep(page, "Draft");
    await expectNoPromote(page, "Approved");
    await expect(page.getByRole("img", { name: "You do not have permission to promote this record to Approved." })).toBeVisible();
  });
});
