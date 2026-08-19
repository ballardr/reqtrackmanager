import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS } from "./helpers";

/**
 * Below 860px (theme.css) the nav rail is unconditionally force-collapsed
 * to icon-only width regardless of the user's manual expand/collapse
 * preference — there isn't room for a full rail, content, and the
 * filter/activity sidebar side by side. The expand/collapse toggle
 * therefore has nothing to do at that width; it must be hidden there
 * rather than left visible and inert, which previously read as a broken
 * button on mobile viewports.
 */
test.describe("nav rail: mobile collapse toggle", () => {
  test("collapse toggle is hidden below the responsive breakpoint, visible above it", async ({ page }) => {
    await page.setViewportSize({ width: 700, height: 900 });
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    await expect(page.getByRole("button", { name: /Collapse navigation|Expand navigation/ })).toBeHidden();
    await expect(page.getByRole("navigation")).toBeVisible();

    await page.setViewportSize({ width: 1280, height: 900 });
    await expect(page.getByRole("button", { name: /Collapse navigation|Expand navigation/ })).toBeVisible();
  });
});
