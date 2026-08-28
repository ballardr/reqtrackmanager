import { expect, test } from "@playwright/test";

/**
 * UX review: the Project Overview dashboard's glance tiles, status pie
 * charts, and stage-progress bars didn't navigate anywhere when clicked.
 * They now deep-link to the Requirements/Change Requests list pre-filtered
 * to match what was clicked. Verified against the demo dataset (scripts/
 * seed_demo_data.py), which seeds requirements at varied lifecycle stages
 * and change requests in varied outcomes so every widget has a non-zero
 * count to click through.
 */
async function loginAsDemoAdminAndOpenProject(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo.admin@example.com");
  await page.getByLabel("Password").fill("DemoDemo123!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/projects(\/|$)/);

  await page.goto("/projects");
  // Solstice Cloud Platform, not Falcon-3 Inspection Drone: Falcon-3 has a
  // per-project terminology override (Requirement -> "Spec", Change Request
  // -> "ECR", seed_demo_data.py) which would make label-text-based locators
  // below stop matching — Solstice uses the default terminology this spec
  // relies on.
  await page.getByRole("link", { name: "Solstice Cloud Platform" }).first().click();
  await page.waitForURL(/\/projects\/[^/]+$/);
}

test("dashboard glance tile navigates to the requirements list", async ({ page }) => {
  await loginAsDemoAdminAndOpenProject(page);

  const tiles = page.locator(".grid-metrics");
  await tiles.getByRole("link", { name: "Requirements" }).click();
  await page.waitForURL(/\/requirements$/);
  await expect(page.getByLabel("Status")).toHaveValue("");
});

test("dashboard status chart segment navigates to the requirements list filtered to that status", async ({ page }) => {
  await loginAsDemoAdminAndOpenProject(page);

  // Click the first legend row under the "Requirements by status" chart.
  const chartCard = page.locator(".card", { hasText: "Requirements by status" });
  const firstSegmentButton = chartCard.getByRole("button").first();
  const segmentLabel = (await firstSegmentButton.textContent())?.trim();
  await firstSegmentButton.click();

  // The `?status=` param is consumed and stripped by RequirementsPage's own
  // deep-link effect immediately on arrival (same pattern as the pre-
  // existing `?new=1` deep link) — assert the resulting filter *state*
  // (the Status select's value), not that the query param is still in the
  // URL by the time this polls.
  await page.waitForURL(/\/requirements$/);
  const statusSelect = page.getByLabel("Status");
  await expect(statusSelect).not.toHaveValue("");
  // The requirements list's status option text should match the clicked segment's label.
  const selectedOptionText = await statusSelect.locator("option:checked").textContent();
  expect(selectedOptionText?.trim()).toBe(segmentLabel);
});

test("dashboard change-request tile navigates to the change requests list filtered to that status", async ({ page }) => {
  await loginAsDemoAdminAndOpenProject(page);

  const tiles = page.locator(".grid-metrics");
  await tiles.getByRole("link", { name: "Change requests approved" }).click();
  // Same param-stripped-on-arrival behaviour as above — assert the landing
  // page and the resulting filter state, not a lingering query string.
  await page.waitForURL(/\/change-requests$/);
  await expect(page.getByLabel("Status")).toHaveValue("approved");
});

/**
 * Regression test for a mount-time race that used to leave the *rendered
 * list* out of sync with the (correctly-set) filter dropdown after a
 * dashboard glance-tile navigation — the tests above only ever asserted
 * the dropdown's value, which is exactly the gap that let this ship: the
 * manual workaround ("toggle the filter and back") always fixed the
 * dropdown-vs-list mismatch by forcing a fresh, single fetch, so the
 * dropdown alone never caught it.
 *
 * `RequirementsPage.tsx` used to seed `statusFilter=""` and set it to the
 * deep-linked value in a *separate* effect that ran after mount, so two
 * requirements-list fetches fired on landing — one unfiltered (kicked off
 * first, before the deep-link effect had run) and one filtered to
 * `status=completed` (kicked off second, once it had) — with no
 * request-sequencing guard, so whichever response resolved last simply
 * overwrote the other, win or lose. That race is real but *timing*-
 * dependent, so reproducing it reliably needs the unfiltered request's
 * response artificially delayed here — against the fixed code (which
 * seeds the filter directly from the URL on initial render) only the one
 * filtered request is ever issued, so the delayed route below never even
 * matches and this passes; against the old two-effect shape, the delayed,
 * stale unfiltered response is guaranteed to resolve last and overwrite
 * the correct one, so this reliably fails.
 *
 * Navigates via the "Requirements by status" pie-chart's first legend
 * segment, same as the sibling test above, rather than the dashboard's
 * "% Completed" metrics tile — Solstice Cloud Platform's seeded mix
 * (`CLOUD_REQUIREMENTS`, `seed_demo_data.py`) happens to have zero
 * `completed` requirements, which would make that specific tile land on an
 * always-empty list and prove nothing; the chart only ever lists statuses
 * with at least one requirement, so its first segment is guaranteed
 * non-empty regardless of which status that happens to be.
 */
test("dashboard glance tile with a non-default filter renders the correctly-filtered list on first paint", async ({
  page,
}) => {
  await loginAsDemoAdminAndOpenProject(page);

  await page.route("**/api/v1/projects/*/requirements?*", async (route) => {
    const url = new URL(route.request().url());
    if (!url.searchParams.has("status")) {
      await new Promise((resolve) => setTimeout(resolve, 400));
    }
    await route.continue();
  });

  const chartCard = page.locator(".card", { hasText: "Requirements by status" });
  const firstSegmentButton = chartCard.getByRole("button").first();
  const segmentLabel = (await firstSegmentButton.textContent())?.trim();
  expect(segmentLabel).toBeTruthy();
  await firstSegmentButton.click();

  // `/\/requirements$/`, not a pattern including `?status=` — same
  // reasoning as the sibling chart-segment test above: the query param is
  // consumed and stripped by `RequirementsPage`'s own deep-link effect
  // (`setSearchParams(..., { replace: true })`) essentially immediately on
  // arrival, so a `waitForURL` pattern that requires the query string
  // still being present can lose the race and hang past the test timeout
  // waiting for a URL shape that already came and went before this line
  // even started polling.
  await page.waitForURL(/\/requirements$/);
  const statusSelect = page.getByLabel("Status");
  await expect(statusSelect).not.toHaveValue("");
  const selectedOptionText = await statusSelect.locator("option:checked").textContent();
  expect(selectedOptionText?.trim()).toBe(segmentLabel);

  // The regression itself: not just the dropdown, but the rendered list
  // and the persistent result count (2026-08 UX audit roadmap:
  // `ResultCount`) must already reflect the filter on first paint. Scoped
  // to the main list column (`.side-grid`'s first child), not the
  // FilterPanel sidebar, so the Status `<select>`'s own matching `<option>`
  // text can't false-match.
  const mainColumn = page.locator(".side-grid > div").first();
  const statusBadges = mainColumn.locator("button.badge");
  await expect(statusBadges.first()).toBeVisible();
  const badgeTexts = await statusBadges.allTextContents();
  expect(badgeTexts.length).toBeGreaterThan(0);
  for (const text of badgeTexts) {
    expect(text.trim()).toBe(segmentLabel);
  }
  // The unfiltered-response-wins failure mode collapses `ResultCount` back
  // to "N total" (its own, un-narrowed `X-Total-Count` reads as if no
  // filter were applied) instead of "Showing N matching · M total".
  await expect(page.getByText(/^Showing \d+ matching · \d+ total$/)).toBeVisible();
});
