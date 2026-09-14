import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS } from "./helpers";

/**
 * Below 860px (theme.css/`useNarrowViewport`, matching the nav rail's own
 * mobile breakpoint per mobile-nav-rail.spec.ts) `ResourceMenu`'s vertical
 * link list is replaced with a single `<select>` (platform-review-2026-09:
 * Org Admin alone has up to 10 groups, forcing a scroll past the whole menu
 * on a phone-width viewport before reaching the selected group's own
 * content). Org Admin is the motivating, worst-case example — real content,
 * not a demo fixture — so this exercises the actual page rather than
 * Storybook's synthetic three-group `ResourceMenu.stories.tsx` fixture.
 */
test.describe("resource menu: mobile dropdown collapse", () => {
  test("Org Admin's section list collapses to a dropdown below the breakpoint, and switching groups navigates", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 400, height: 900 });
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.getByRole("link", { name: "My organisations" }).click();
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    await expect(page).toHaveURL(/\/orgs\/[0-9a-f-]+\/admin/);

    // Vertical link list is gone entirely below the breakpoint — a
    // dropdown stands in for it, not just a differently-styled list.
    await expect(page.getByRole("navigation", { name: "Organisation admin sections" })).toBeHidden();
    await expect(page.getByRole("link", { name: "Users", exact: true })).toBeHidden();
    const dropdown = page.getByRole("combobox", { name: "Organisation admin sections" });
    await expect(dropdown).toBeVisible();
    await expect(dropdown).toHaveValue("overview");

    await dropdown.selectOption({ label: "Users" });
    await expect(page).toHaveURL(/\/orgs\/[0-9a-f-]+\/admin\/users/);
    await expect(dropdown).toHaveValue("users");
    // The organisation name stays visible as the page's own <h1> across the
    // switch — same regression `admin-page-titles-and-version-footer.spec.ts`
    // pins for the desktop link list.
    await expect(page.getByRole("heading", { level: 1, name: ORG_NAMES.alpha })).toBeVisible();

    // Widening back past the breakpoint restores the link list and hides
    // the dropdown — the same two-way check mobile-nav-rail.spec.ts runs
    // for the nav rail's own collapse.
    await page.setViewportSize({ width: 1280, height: 900 });
    await expect(dropdown).toBeHidden();
    await expect(page.getByRole("link", { name: "Users", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Users", exact: true })).toHaveAttribute("aria-current", "page");
  });
});
