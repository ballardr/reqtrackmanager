import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: the requirements list can be narrowed by search
 * (name/ID, U-E-01), status/target-version/category filters, and
 * has-comments/only-watched checkboxes; the tile/list view choice persists
 * across a reload (synced server-side, not just localStorage).
 *
 * badge-filters.spec.ts already covers the status-badge click-to-filter
 * interaction specifically — this spec covers the FilterPanel's remaining
 * controls, which aren't covered anywhere else.
 *
 * RequirementsPage's fetch effect has no request-cancellation guard, so
 * firing a new filtered fetch while a previous one is still in flight can
 * let the older response resolve later and overwrite the newer one —
 * `settled()` waits for the known-unfiltered baseline (both HW-FN-001 and
 * a requirement NOT matching the previous filter are visible) before the
 * next filter change, so each change starts from a confirmed-quiescent list.
 */
test.describe("requirements list filters and view-mode persistence", () => {
  test("search, status/category filters, has-comments/watched checkboxes, and view-mode persistence", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.getByText(PROJECT_NAMES.alpha1).click();
    await page.getByRole("link", { name: "Requirements", exact: true }).click();

    async function settled() {
      await expect(page.getByText("HW-FN-001")).toBeVisible();
      await expect(page.getByRole("link", { name: "Must expose a health-check endpoint", exact: true })).toBeVisible();
    }

    await settled();

    await test.step("search narrows by name substring and by unique ID", async () => {
      const searchBox = page.getByPlaceholder("Search by name or ID");
      // Uses "Must expose a health-check endpoint" rather than HW-FN-001's
      // requirement — change-request-approval-separation.spec.ts approves a
      // CR that renames HW-FN-001, so its name isn't stable across the
      // suite. HW-FN-001's *code* is still stable, so it's used for the
      // by-ID half below instead.
      await searchBox.fill("health-check endpoint");
      await expect(page.getByRole("link", { name: "Must expose a health-check endpoint", exact: true })).toBeVisible();
      await expect(page.getByText("HW-FN-001")).toHaveCount(0);

      await searchBox.fill("HW-FN-001");
      await expect(page.getByText("HW-FN-001")).toBeVisible();

      await searchBox.fill("zzz-nothing-matches-zzz");
      await expect(page.getByText("No requirements to show.")).toBeVisible();
      await searchBox.fill("");
      await settled();
    });

    await test.step("status filter narrows the list", async () => {
      await page.getByLabel("Status").selectOption("approved");
      await expect(page.getByText("HW-FN-001")).toBeVisible();
      await expect(page.getByText("Must expose a health-check endpoint")).toHaveCount(0);
      await page.getByLabel("Status").selectOption("");
      await settled();
    });

    await test.step("category filter narrows the list", async () => {
      const categorySelect = page.getByLabel("Category");
      const options = await categorySelect.locator("option").allTextContents();
      const firstRealCategory = options.find((o) => o.trim() && o !== "All");
      if (firstRealCategory) {
        await categorySelect.selectOption({ label: firstRealCategory });
        await expect(page.getByText("No requirements to show.")).toHaveCount(0);
        await categorySelect.selectOption("");
        await settled();
      }
    });

    await test.step("has-comments-only and only-watched checkboxes toggle without erroring", async () => {
      await page.getByLabel("Has comments").check();
      await page.getByLabel("Has comments").uncheck();
      await page.getByLabel("Only watched").check();
      await page.getByLabel("Only watched").uncheck();
      await settled();
    });

    await test.step("switching to list view persists across a reload", async () => {
      // Wait for the PATCH to actually settle before reloading — a bare
      // click() races the async save (AuthContext.tsx's setUiPreference is
      // fire-and-forget) against the immediate reload below, which can
      // observe the pre-save state if it wins the race — same fix as
      // preferences-and-theme.spec.ts's "pronouns save and persist" step.
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/auth/me/preferences") && r.request().method() === "PATCH"),
        page.getByRole("button", { name: "List view" }).click(),
      ]);
      await expect(page.getByRole("button", { name: "List view" })).toHaveAttribute("aria-pressed", "true");
      await page.reload();
      await expect(page.getByRole("button", { name: "List view" })).toHaveAttribute("aria-pressed", "true");
      await page.getByRole("button", { name: "Tile view" }).click();
    });
  });
});
