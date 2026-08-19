import { expect, test } from "@playwright/test";

import { loginAs, logout, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: a requirement can be given a scheduled review (C-R-06),
 * the assigned reviewer sees it on both their personal due list (C-R-09,
 * filtered per C-R-10) and the project's due list, and recording an outcome
 * (C-R-07) is gated to that reviewer or a project manager and requires a
 * comment when the outcome is "failed".
 *
 * A brand-new requirement is created for this test (rather than reusing a
 * seeded one) so it's unaffected by whatever lock state other specs in this
 * suite leave Alpha-1's other requirements in.
 */
test.describe("requirement review scheduling", () => {
  test("PM schedules a review, the reviewer sees it due and records an outcome", async ({ page }) => {
    const reqName = `Must maintain calibration accuracy (E2E ${Date.now()})`;
    let projectId = "";
    let requirementId = "";

    await test.step("PM creates a requirement and schedules a past-due review assigned to a stakeholder", async () => {
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      await page.getByText(PROJECT_NAMES.alpha1).click();
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await page.getByRole("button", { name: "New Requirement" }).click();
      await page.getByRole("button", { name: "Add one" }).click();
      // The create form is a `SidePanel` portalled to the end of
      // `document.body` — scope to it rather than an unscoped
      // `getByRole("combobox").first()`, which would otherwise resolve to
      // the filter sidebar's own Status select (it precedes the panel in
      // DOM order once the form is a portal instead of an inline block).
      const panel = page.getByRole("dialog", { name: "New Requirement" });
      await expect(panel.getByRole("combobox").first()).toContainText("Hardware");
      await page.getByPlaceholder("Name", { exact: true }).fill(reqName);
      await page.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByText(reqName)).toBeVisible();
      await page.getByText(reqName).click();

      projectId = page.url().match(/projects\/([0-9a-f-]+)/)![1];
      requirementId = page.url().match(/requirements\/([0-9a-f-]+)/)![1];

      await page.getByLabel("Review date").fill("2024-01-01");
      await page.getByLabel("Reminder lead time (days)").fill("7");
      await page
        .getByLabel("Assigned reviewer")
        .selectOption({ label: `${PERSONAS.stakeholderAlpha.name} (${PERSONAS.stakeholderAlpha.email})` });
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Review date: 2024-01-01")).toBeVisible();
      await expect(page.getByText(`Assigned reviewer: ${PERSONAS.stakeholderAlpha.name}`)).toBeVisible();
    });

    await test.step("a project member who isn't the reviewer or a PM cannot record the outcome via a direct API call", async () => {
      await logout(page);
      await loginAs(page, PERSONAS.memberAlphaBeta.email);
      const memberToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const resp = await page.request.post(
        `http://localhost:8000/api/v1/projects/${projectId}/requirements/${requirementId}/reviews`,
        { headers: { Authorization: `Bearer ${memberToken}` }, data: { outcome: "met", comment: null } }
      );
      expect(resp.status()).toBe(403);
    });

    await test.step("failing the review without a comment is rejected server-side, not just left to the UI", async () => {
      await logout(page);
      await loginAs(page, PERSONAS.stakeholderAlpha.email);
      const reviewerToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const failResp = await page.request.post(
        `http://localhost:8000/api/v1/projects/${projectId}/requirements/${requirementId}/reviews`,
        { headers: { Authorization: `Bearer ${reviewerToken}` }, data: { outcome: "failed", comment: "" } }
      );
      expect(failResp.status()).toBe(400);
    });

    await test.step("the assigned reviewer sees the requirement on their personal due list", async () => {
      await page.goto("/my-reviews");
      await expect(page.getByRole("link", { name: reqName })).toBeVisible();
    });

    await test.step("the PM sees it on the project's due list, filterable by component and reviewer", async () => {
      await logout(page);
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      await page.getByText(PROJECT_NAMES.alpha1).click();
      await page.getByRole("link", { name: "Requirements due for review", exact: true }).click();
      await expect(page.getByRole("link", { name: reqName })).toBeVisible();
      await page.getByRole("combobox").nth(1).selectOption({ label: PERSONAS.stakeholderAlpha.name });
      await expect(page.getByRole("link", { name: reqName })).toBeVisible();
    });

    await test.step("the reviewer records a 'met' outcome through the real UI, and it drops off both due lists", async () => {
      await logout(page);
      await loginAs(page, PERSONAS.stakeholderAlpha.email);
      await page.goto(`/projects/${projectId}/requirements/${requirementId}`);
      await page.getByRole("button", { name: "Submit review" }).click();
      await expect(page.getByRole("button", { name: "Submit review" })).toBeVisible();
      await page.goto("/my-reviews");
      await expect(page.getByRole("link", { name: reqName })).toHaveCount(0);
    });

    await test.step("it is also gone from the PM's project due list", async () => {
      await logout(page);
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      await page.getByText(PROJECT_NAMES.alpha1).click();
      await page.getByRole("link", { name: "Requirements due for review", exact: true }).click();
      await expect(page.getByRole("link", { name: reqName })).toHaveCount(0);
    });
  });
});
