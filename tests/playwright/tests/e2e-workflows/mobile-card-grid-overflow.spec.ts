import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS } from "./helpers";

/**
 * The tile/card views on Requirements, Change Requests, Project List, and
 * Favourites all used a fixed `minmax(280px, 1fr)` grid track. Below
 * roughly 431px wide the collapsed nav rail (56px) plus `.app-content`'s
 * own padding (24px each side) leaves less than 280px for the grid itself,
 * so the single column that fits was forced wider than its container —
 * concretely, ~9px of horizontal overflow at a 375px viewport (iPhone
 * SE/mini class), producing a page-level horizontal scrollbar. Fixed by
 * clamping the track minimum to `min(280px, 100%)` so it never exceeds
 * whatever width is actually available. This only asserts the absence of
 * horizontal overflow at a narrow width — it isn't a visual/layout test.
 */
test.describe("mobile: card/tile grids never overflow the viewport width", () => {
  test.use({ viewport: { width: 375, height: 900 } });

  async function expectNoHorizontalOverflow(page: import("@playwright/test").Page) {
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth
    );
    expect(overflow).toBeLessThanOrEqual(0);
  }

  test("Requirements tile view", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/projects");
    await page.getByRole("link", { name: /Alpha-1/ }).click();
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    await page.getByRole("button", { name: "Tile view" }).click();
    await expect(page.locator(".card").first()).toBeVisible();
    await expectNoHorizontalOverflow(page);

    // View mode is a server-persisted per-user preference (useViewMode),
    // not local to this page load — leaving it on "tiles" would affect
    // this shared persona in every later spec that assumes list view
    // (e.g. project-history.spec.ts's openRequirementByCode helper, which
    // isn't tile-view-safe). Restore it for any later spec.
    await page.getByRole("button", { name: "List view" }).click();
  });

  test("Change Requests tile view", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/projects");
    await page.getByRole("link", { name: /Alpha-1/ }).click();
    await page.getByRole("link", { name: "Change requests", exact: true }).click();
    await page.getByRole("button", { name: "Tile view" }).click();
    await expect(page.locator(".card").first()).toBeVisible();
    await expectNoHorizontalOverflow(page);

    // Same server-persisted view-mode caveat as the Requirements test above.
    await page.getByRole("button", { name: "List view" }).click();
  });

  test("Project List tile view", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/projects");
    await expect(page.locator(".card").first()).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });

  test("Favourites card grid", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/projects");
    const star = page.getByRole("button", { name: /favourite/i }).first();
    await star.click();
    // Layout's nav-rail "Favourites" link only appears once its own
    // `hasFavourites` probe re-fires on arrival at /projects or
    // /favourites — navigating directly is more reliable here than
    // waiting for a rail link that may not have appeared yet.
    await page.goto("/favourites");
    await expect(page.locator(".card").first()).toBeVisible();
    await expectNoHorizontalOverflow(page);

    // Restore state for any later spec that assumes a clean slate.
    await page.getByRole("button", { name: /favourite/i }).first().click();
  });
});
