import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { createRequest, projectBase, requestLevels, setUpOrg } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: someone filling in a request sees what each level they choose does to the score while they choose
 * it (and what a model still needs), and the owner field costs one line, not three.
 *
 * Builds its own disposable org (see `./helpers.ts`), so it depends on no seeded state.
 */
test.describe("Enhancement request form: live scores and compact owner", () => {
  test("scores appear as levels are chosen, say what is still missing, and the owner takes one row", async ({ page }) => {
    const { project } = await setUpOrg(page, "FeedbackPreview");
    await page.goto(`/projects/${project.id}/modules/product_feedback/requests`);
    await page.getByRole("button", { name: "New request" }).click();
    const dialog = page.getByRole("dialog", { name: /New enhancement request/ });
    const scores = dialog.getByRole("region", { name: "Scores" });

    await test.step("with nothing chosen every model reads Not scored, and hovering says what it needs", async () => {
      await expect(scores.getByLabel("Not scored. Needs Impact, Confidence, Ease to be scored")).toHaveText("Not scored");
      await expect(scores.getByText(/needs/i)).toHaveCount(0); // no inline "needs" text
      await scores.getByLabel("Not scored. Needs Impact, Confidence, Ease to be scored").hover();
      await expect(page.getByText("Needs Impact, Confidence, Ease to be scored", { exact: true })).toBeVisible();
    });

    await test.step("choosing the levels a model needs scores it, without saving", async () => {
      await dialog.getByLabel("Impact", { exact: true }).selectOption({ label: "High" });
      await dialog.getByLabel("Confidence", { exact: true }).selectOption({ label: "High" });
      await dialog.getByLabel("Ease", { exact: true }).selectOption({ label: "Easy" });
      await expect(scores.getByLabel("Not scored. Needs Impact, Confidence, Ease to be scored")).toHaveCount(0);
      await expect(scores.getByText(/· \d+/).first()).toBeVisible();
      await expect(scores.getByLabel(/^Not scored\. Needs Reach/).first()).toBeVisible(); // RICE still lacks Reach and Effort
    });

    await test.step("a level's meaning is a (?) tooltip, not a note under the field", async () => {
      const help = dialog.getByRole("button", { name: "Help: Impact" });
      await help.hover();
      await expect(page.getByRole("tooltip")).toContainText("High"); // every level of the axis, not only the chosen one
      await expect(page.getByRole("tooltip")).toContainText("Low");
    });

    await test.step("Link to is a bold title, like the sections above it", async () => {
      await expect(dialog.locator("label strong", { hasText: "Link to" })).toBeVisible();
    });

    await test.step("the owner label, value and search share one row", async () => {
      const value = await dialog.getByText("Unassigned", { exact: true }).boundingBox();
      const search = await dialog.getByLabel("Request owner").boundingBox();
      expect(value && search).toBeTruthy();
      expect(Math.abs((value!.y + value!.height / 2) - (search!.y + search!.height / 2))).toBeLessThan(12);
    });
  });

  test("an edit previews with the request's own demand and its saved levels", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "FeedbackPreviewEdit");
    const { level } = await requestLevels(page, project.id, adminHeaders);
    const request = await createRequest(page, projectBase(project.id), adminHeaders, {
      title: `Scored ask ${suffix}`,
      levels: {
        reach: level("reach", "Many"), impact: level("impact", "High"), confidence: level("confidence", "High"),
        ease: level("ease", "Easy"), effort: level("effort", "Medium"),
      },
    });
    await page.goto(`/projects/${project.id}/modules/product_feedback/requests/${request.id}`);
    await page.getByRole("button", { name: /^Edit/ }).first().click();
    const scores = page.getByRole("dialog").getByRole("region", { name: "Scores" });
    await expect(scores.getByText(/· \d+/).first()).toBeVisible();
    await expect(scores.getByLabel(/^Not scored\. Needs/)).toHaveCount(0);

    await page.getByRole("dialog").getByLabel("Ease", { exact: true }).selectOption({ label: "Not scored" });
    await expect(scores.getByLabel(/Needs Ease/).first()).toBeVisible();
  });
});
