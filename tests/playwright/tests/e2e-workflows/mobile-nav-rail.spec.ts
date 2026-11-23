import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS } from "./helpers";

/**
 * Below 860px (theme.css) the nav rail is forced to icon-only width regardless of the manual expand/collapse
 * preference, so the expand/collapse toggle has nothing to do there and is hidden rather than left visible and inert.
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
