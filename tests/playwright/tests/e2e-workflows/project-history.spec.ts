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

    // Converted onto the shared `ActivityPanel` component (2026-08 UX audit
    // roadmap row 515) — each row now links to the requirement/change
    // request it's about (`getLink`/`activityEntryLink`), the same way the
    // project overview's own activity card, and this page's own previous
    // hand-rolled markup, already did; this pins that the shared component
    // still carries it through. Filtered to "Requirement" (a control this
    // spec's own next step already exercises) rather than asserting on the
    // unfiltered default view, whose page-1 contents depend on how much
    // other activity the shared Alpha org has accumulated from the rest of
    // this suite by the time this spec happens to run.
    await test.step("activity rows link back to the requirement each change is about", async () => {
      await page.getByLabel("Type").selectOption("requirement");
      const requirementLink = page.locator("main").getByRole("link").first();
      await expect(requirementLink).toBeVisible();
      await expect(requirementLink).toHaveAttribute("href", /\/requirements\//);
      await page.getByLabel("Type").selectOption("");
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
      // `ProjectHistoryPage.tsx`'s `since` state has no request-
      // cancellation guard (the same "no request-cancellation guard"
      // characteristic this file's own docstring already calls out
      // elsewhere in the suite, e.g. `RequirementsPage`) — a native
      // `datetime-local` input's `fill()` can dispatch more than one
      // intermediate `input` event as it fills day/month/year/time
      // segments, each triggering its own `/changes` fetch. Racing a
      // single `waitForResponse` against that can resolve on an
      // intermediate (not-yet-fully-future) request and assert before the
      // final, correct one has actually landed — `toPass()` retries the
      // assertion instead of trusting the first `/changes` response to be
      // the last one.
      await page.getByLabel("Since").fill(future.toISOString().slice(0, 16));
      await expect(async () => {
        await expect(page.getByText("No changes in this range.")).toBeVisible();
      }).toPass();
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
