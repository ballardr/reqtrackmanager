import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS } from "./helpers";

/**
 * Job to be done: `RequirementDetailPage`'s previously-separate "Change
 * log" (a table of this requirement's own `RequirementVersion` rows) and
 * "Activity" (the general audit-log feed, including but not limited to
 * those same version changes) cards are now one card with a view toggle
 * (2026-08 UX audit roadmap item 516) — both renderings still exist, the
 * toggle only changes which one is on screen, and the chosen view is
 * remembered per-user across page loads via `useUiPreference` (server-
 * synced, the same mechanism the tile/list view toggles elsewhere already
 * use), not just local component state.
 *
 * Creates its own throwaway requirement rather than reusing seeded data —
 * editing it to produce a real version-history/activity entry is the point
 * of the test, and other specs may depend on seeded requirements' history
 * staying as-is.
 */
test.describe("requirement detail: merged History/Activity card and its view toggle", () => {
  test("both views render the same underlying event; the chosen view persists across a reload", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/projects");
    await page.getByRole("link", { name: /Alpha-1/ }).click();
    await page.getByRole("link", { name: "Requirements", exact: true }).click();

    const name = `E2E History Activity Toggle ${Date.now()}`;
    await page.getByRole("button", { name: "New requirement" }).click();
    await page.getByPlaceholder("Name", { exact: true }).fill(name);
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await page.getByText(name).click();

    await test.step("editing the requirement produces a version-history row and an activity entry", async () => {
      await page.getByLabel("Reasoning", { exact: true }).fill("Updated reasoning for the toggle test.");
      await page.getByPlaceholder("Reason for change").fill("E2E toggle test edit");
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Updated reasoning for the toggle test.")).toBeVisible();
    });

    await test.step("defaults to the Activity view, showing the edit as an audit-log entry", async () => {
      await expect(page.getByRole("heading", { name: "Activity", level: 2 })).toBeVisible();
      await expect(page.getByText(/updated/i).first()).toBeVisible();
      await expect(page.getByRole("button", { name: "Activity" })).toHaveAttribute("aria-pressed", "true");
    });

    await test.step("toggling to Version history shows the same edit as a version row, not a second copy of the card", async () => {
      await page.getByRole("button", { name: "Version history" }).click();
      await expect(page.getByRole("heading", { name: "Version history", level: 2 })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Activity", level: 2 })).not.toBeVisible();
      await expect(page.getByRole("cell", { name: "E2E toggle test edit" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Version history" })).toHaveAttribute("aria-pressed", "true");
    });

    await test.step("the chosen view (Version history) survives a reload, via the server-synced ui_preferences bag", async () => {
      await page.reload();
      await expect(page.getByRole("heading", { name: "Version history", level: 2 })).toBeVisible();
      await expect(page.getByRole("cell", { name: "E2E toggle test edit" })).toBeVisible();
    });

    await test.step("switching back to Activity works the same way after a reload", async () => {
      await page.getByRole("button", { name: "Activity" }).click();
      await expect(page.getByRole("heading", { name: "Activity", level: 2 })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Version history", level: 2 })).not.toBeVisible();
    });
  });
});
