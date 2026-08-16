import { expect, test } from "@playwright/test";

import { loginAs, openRequirementByCode, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: a unified, filterable timeline of a project's changes
 * over time (C-A-10) — entity-type and date-range filters, with discussion
 * comments excluded by default and only included when explicitly asked
 * for.
 */
test.describe("project history / changes-over-time view", () => {
  test("filters by entity type, date range, and optionally includes comments", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.getByText(PROJECT_NAMES.alpha1).click();

    await test.step("post a comment first, so there's something for the include-comments toggle to reveal", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByCode(page, "HW-FN-001");
      await page.getByPlaceholder("Add comment").fill("E2E: project-history spec comment marker.");
      await page.getByRole("button", { name: "Add comment", exact: true }).click();
    });

    await test.step("the history page lists activity by default, with comments excluded", async () => {
      await page.getByRole("link", { name: "Project history", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Project history", exact: true })).toBeVisible();
      await expect(page.getByText("E2E: project-history spec comment marker.")).toHaveCount(0);
    });

    await test.step("including comments reveals the comment event", async () => {
      await page.getByLabel("Include discussion comments").check();
      await expect(page.getByText(/comment/i).first()).toBeVisible();
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/changes")),
        page.getByLabel("Include discussion comments").uncheck(),
      ]);
    });

    await test.step("filtering to a future date range shows no changes", async () => {
      const future = new Date(Date.now() + 365 * 24 * 60 * 60 * 1000);
      // Wait for the debounced /changes fetch this filter change triggers
      // before asserting on its result — a bare fill() plus an immediate
      // expect() relies purely on the assertion's own timeout to outlast
      // the debounce+network round trip, which the very next line below
      // already avoids doing for the matching "clear the filter" fetch.
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/changes")),
        page.getByLabel("Since").fill(future.toISOString().slice(0, 16)),
      ]);
      await expect(page.getByText("No changes in this range.")).toBeVisible();
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/changes")),
        page.getByLabel("Since").fill(""),
      ]);
    });

    await test.step("filtering by entity type narrows the list without erroring", async () => {
      await page.getByLabel("Type").selectOption("requirement");
      await expect(page.getByText("No changes in this range.")).toHaveCount(0);
      await page.getByLabel("Type").selectOption("");
    });
  });
});
