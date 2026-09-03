import { expect, test } from "@playwright/test";

/**
 * `ResultCount`'s two display states and `FilterPanel`'s header/collapsible-
 * body restructure (2026-08 UX audit roadmap: persistent "showing X of Y"
 * result count) — verified against the demo dataset (scripts/
 * seed_demo_data.py) on `RequirementsPage`, which seeds requirements at
 * varied lifecycle statuses so a status filter and a name search are both
 * guaranteed to narrow the list without emptying it.
 */

const apiBaseUrl = "http://localhost:8000";
const DEMO_ADMIN_EMAIL = "demo.admin@example.com";
const DEMO_ADMIN_PASSWORD = "DemoDemo123!";

async function loginAsDemoAdminAndOpenRequirements(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(DEMO_ADMIN_EMAIL);
  await page.getByLabel("Password").fill(DEMO_ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/projects(\/|$)/);

  await page.goto("/projects");
  // Solstice Cloud Platform: default terminology, no per-project override —
  // same choice `dashboard-navigation.spec.ts` makes and for the same
  // reason (a terminology override would make this spec's literal-English
  // locators, e.g. "Requirements", stop matching).
  await page.getByRole("link", { name: "Solstice Cloud Platform" }).first().click();
  await page.getByRole("link", { name: "Requirements", exact: true }).click();
  await page.waitForURL(/\/requirements$/);
  // `total`/`totalUnfiltered` both start at 0 before the first fetch
  // resolves, and "0 total" matches `resultCountLocator`'s own `/total$/`
  // pattern just as validly as any real count — waiting for the page's own
  // loading `Spinner` to clear avoids reading that transient pre-fetch
  // "0 total" render instead of the settled one. Matched by text, not
  // just `role="status"` — `Toast`'s own empty live region shares that
  // role and would otherwise make this locator ambiguous.
  await expect(page.getByText("Loading…")).toBeHidden();
}

/** Reads the current, single result-count line from `FilterPanel`'s header
 * — scoped to `.side-grid` so a `<select>` option's own text (e.g. the
 * Status dropdown's "Completed") can never false-match. */
function resultCountLocator(page: import("@playwright/test").Page) {
  return page.locator(".side-grid").getByText(/total$/);
}

/** `FilterPanel` itself — `.side-grid`'s second child (the main list
 * column is the first). Scoping the Status field's locator to just this
 * container, rather than the whole page, matters here specifically: a
 * `getByLabel("Status")` search across the *whole* page can accidentally
 * match a bulk-select row checkbox in the main column whose accessible
 * name happens to contain the substring "status" (Solstice Cloud
 * Platform's seeded "API-REL-012 Provide a status page..." requirement) —
 * `exact: true` isn't a fix here, since the Status `<select>`'s own
 * implicit-label accessible name already includes its *currently selected
 * option's* text (e.g. "StatusApproved"), which changes with the filter
 * and would never equal a fixed "Status" string. */
function filterPanelLocator(page: import("@playwright/test").Page) {
  return page.locator(".side-grid > div").nth(1);
}

test("ResultCount shows total-only by default, matching-plus-total once a status filter is applied, and total-only again once cleared", async ({
  page,
}) => {
  await loginAsDemoAdminAndOpenRequirements(page);

  const resultCount = resultCountLocator(page);
  await expect(resultCount).toHaveText(/^\d+ total$/);
  const baselineTotal = Number((await resultCount.textContent())?.match(/^(\d+) total$/)?.[1]);
  expect(baselineTotal).toBeGreaterThan(0);

  // Picks whichever status the first rendered row actually has, rather
  // than hardcoding a status value that may not exist in the seeded data
  // (e.g. "completed" — Solstice Cloud Platform's `CLOUD_REQUIREMENTS` mix
  // happens to have zero) — same reasoning as `dashboard-navigation.spec
  // .ts`'s equivalent chart-segment fix, and mirrors `badge-filters.spec
  // .ts`'s established "click a real row's own badge" pattern for the
  // exact same reason.
  const mainColumn = page.locator(".side-grid > div").first();
  const firstBadge = mainColumn.locator("button.badge").first();
  const statusLabel = (await firstBadge.textContent())?.trim();
  expect(statusLabel).toBeTruthy();
  await firstBadge.click();
  await expect(resultCount).toHaveText(/^Showing \d+ matching · \d+ total$/);
  const filteredText = await resultCount.textContent();
  const match = filteredText?.match(/^Showing (\d+) matching · (\d+) total$/);
  // The unfiltered total in the "matching" state must be the exact same
  // mandatory-scope figure as the no-filter baseline above — narrowing the
  // list must never move the denominator, only the numerator.
  expect(Number(match?.[2])).toBe(baselineTotal);
  expect(Number(match?.[1])).toBeGreaterThan(0);
  expect(Number(match?.[1])).toBeLessThan(baselineTotal);

  await filterPanelLocator(page).getByLabel("Status").selectOption("");
  await expect(resultCount).toHaveText(`${baselineTotal} total`);
});

test("ResultCount's matching count re-fetches as the user types in the relocated search box", async ({ page }) => {
  await loginAsDemoAdminAndOpenRequirements(page);

  const resultCount = resultCountLocator(page);
  await expect(resultCount).toHaveText(/^\d+ total$/);
  const baselineTotal = Number((await resultCount.textContent())?.match(/^(\d+) total$/)?.[1]);
  expect(baselineTotal).toBeGreaterThan(0);

  // The search box now lives in `FilterPanel`'s header (moved there from
  // the main content column, 2026-08 UX audit roadmap) — resolve a real,
  // currently-rendered requirement name from the page itself rather than
  // hardcoding demo-data content, so this doesn't drift if the seed script
  // changes what it creates.
  const mainColumn = page.locator(".side-grid > div").first();
  const firstRequirementName = (await mainColumn.locator("a").first().textContent())?.trim();
  expect(firstRequirementName).toBeTruthy();
  const searchTerm = firstRequirementName!.slice(0, Math.min(5, firstRequirementName!.length));

  const searchBox = page.getByPlaceholder("Search by name or ID");
  await expect(searchBox).toBeVisible();
  await searchBox.fill(searchTerm);

  await expect(resultCount).toHaveText(/^Showing \d+ matching · \d+ total$/);
  const searchedText = await resultCount.textContent();
  const searchedMatch = searchedText?.match(/^Showing (\d+) matching · (\d+) total$/);
  expect(Number(searchedMatch?.[2])).toBe(baselineTotal);
  expect(Number(searchedMatch?.[1])).toBeGreaterThan(0);
  // The searched-for name is guaranteed present, so this doesn't assert
  // strictly-less — only that the header actually reflects the search
  // (a non-empty, well-formed "matching" count), which is what a stale/
  // unwired search input would fail to produce.

  await searchBox.fill("");
  await expect(resultCount).toHaveText(`${baselineTotal} total`);
});

test("FilterPanel's filter body starts collapsed below the mobile breakpoint, with the result count and search still visible, and expands/collapses via its toggle", async ({
  page,
}) => {
  // Reset the per-user, cross-device persisted collapse preference this
  // page's `CollapsibleSection` (`sectionKey="requirementsFilters"`) reads
  // before touching the UI at all — `demo.admin@example.com` is a shared
  // fixture account reused across this whole Playwright suite, so a prior
  // run leaving it expanded (e.g. this very test, on an earlier pass) must
  // not make "starts collapsed" fail here; per this project's testing
  // policy, a spec must pass whether it runs alone, first, last, or
  // repeated back-to-back, not only from a freshly seeded database.
  const loginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
    data: { email: DEMO_ADMIN_EMAIL, password: DEMO_ADMIN_PASSWORD },
  });
  const token = (await loginResp.json()).access_token;
  await page.request.patch(`${apiBaseUrl}/api/v1/auth/me/preferences`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { ui_preferences: { "section_collapsed:requirementsFilters": true } },
  });

  // Set before navigating, so the page mounts already narrow — this is a
  // "starts collapsed on load" assertion, not just a live-resize reaction.
  await page.setViewportSize({ width: 400, height: 800 });
  await loginAsDemoAdminAndOpenRequirements(page);

  // Header stays visible: result count and the relocated search box.
  const resultCount = resultCountLocator(page);
  await expect(resultCount).toHaveText(/^\d+ total$/);
  await expect(page.getByPlaceholder("Search by name or ID")).toBeVisible();

  // Body starts collapsed: the Status filter select isn't reachable yet.
  const filterPanel = filterPanelLocator(page);
  await expect(filterPanel.getByLabel("Status")).toBeHidden();
  const toggle = page.getByRole("button", { name: "Filters section" });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");

  await toggle.click();
  await expect(filterPanel.getByLabel("Status")).toBeVisible();
  // `CollapsibleSection` renders a new node for its expanded state rather
  // than toggling an attribute on the same one, so the pre-click `toggle`
  // reference is stale here — re-query it (same pattern as
  // `FilterPanel.stories.tsx`'s `MobileCollapsedByDefault`).
  await expect(page.getByRole("button", { name: "Filters section" })).toHaveAttribute("aria-expanded", "true");

  await page.getByRole("button", { name: "Filters section" }).click();
  await expect(filterPanel.getByLabel("Status")).toBeHidden();
  await expect(page.getByRole("button", { name: "Filters section" })).toHaveAttribute("aria-expanded", "false");

  // Leave the persisted preference collapsed again, matching the reset at
  // the top of this test — the next run (of this test or any other on this
  // shared account) should see the same starting state this one did.
  await page.request.patch(`${apiBaseUrl}/api/v1/auth/me/preferences`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { ui_preferences: { "section_collapsed:requirementsFilters": true } },
  });
});

/**
 * `.side-grid` always renders `FilterPanel` as its second DOM child (main
 * list/table first, filters second) on every page that uses it — fine on
 * desktop's two-column layout, but on the single-column mobile collapse
 * (`@media (max-width: 860px)`, `theme.css`) that put filters visually
 * *after* the entire list, forcing a scroll past everything to reach them.
 * Fixed with a mobile-only `order: -1` on `.side-grid > .filter-panel`
 * (`theme.css`), which doesn't move the DOM, only the rendered position —
 * these tests assert the rendered (visual) top position, not DOM order.
 */
test.describe("FilterPanel renders first on narrow viewports, unaffected on desktop", () => {
  test("Requirements page", async ({ page }) => {
    await page.setViewportSize({ width: 400, height: 900 });
    await loginAsDemoAdminAndOpenRequirements(page);

    const mainColumn = page.locator(".side-grid > div").first();
    const filterPanel = filterPanelLocator(page);
    await expect(filterPanel).toBeVisible();
    await expect(mainColumn).toBeVisible();

    const filterBoxMobile = await filterPanel.boundingBox();
    const mainBoxMobile = await mainColumn.boundingBox();
    expect(filterBoxMobile).not.toBeNull();
    expect(mainBoxMobile).not.toBeNull();
    // Filter panel's rendered top must sit above (a smaller `y` than) the
    // main list column's top on a narrow viewport.
    expect(filterBoxMobile!.y).toBeLessThan(mainBoxMobile!.y);

    // Widening past the 860px breakpoint must restore the untouched desktop
    // layout: side-by-side, not stacked-with-filters-first.
    await page.setViewportSize({ width: 1280, height: 900 });
    await expect(filterPanel).toBeVisible();
    const filterBoxDesktop = await filterPanel.boundingBox();
    const mainBoxDesktop = await mainColumn.boundingBox();
    expect(filterBoxDesktop).not.toBeNull();
    expect(mainBoxDesktop).not.toBeNull();
    // Same row (not reordered above), and to the right of the main column.
    expect(Math.abs(filterBoxDesktop!.y - mainBoxDesktop!.y)).toBeLessThan(5);
    expect(filterBoxDesktop!.x).toBeGreaterThan(mainBoxDesktop!.x);
  });

  test("Change Requests page", async ({ page }) => {
    await page.setViewportSize({ width: 400, height: 900 });
    await page.goto("/login");
    await page.getByLabel("Email").fill(DEMO_ADMIN_EMAIL);
    await page.getByLabel("Password").fill(DEMO_ADMIN_PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.waitForURL(/\/projects(\/|$)/);

    await page.goto("/projects");
    await page.getByRole("link", { name: "Solstice Cloud Platform" }).first().click();
    await page.getByRole("link", { name: "Change requests", exact: true }).click();
    await page.waitForURL(/\/change-requests$/);
    await expect(page.getByText("Loading…")).toBeHidden();

    const mainColumn = page.locator(".side-grid > div").first();
    const filterPanel = filterPanelLocator(page);
    await expect(filterPanel).toBeVisible();
    await expect(mainColumn).toBeVisible();

    const filterBoxMobile = await filterPanel.boundingBox();
    const mainBoxMobile = await mainColumn.boundingBox();
    expect(filterBoxMobile).not.toBeNull();
    expect(mainBoxMobile).not.toBeNull();
    expect(filterBoxMobile!.y).toBeLessThan(mainBoxMobile!.y);
  });
});
