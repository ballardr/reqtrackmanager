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

  const tiles = page.locator(".overview-grid");
  await tiles.getByRole("link", { name: "% Completed" }).click();
  await page.waitForURL(/\/requirements(?:\?.*)?$/);
  await expect(page.getByLabel("Status", { exact: true })).toHaveValue("");
});

test("dashboard total-records legend row navigates to that type's list", async ({ page }) => {
  await loginAsDemoAdminAndOpenProject(page);

  const chartCard = page.locator(".card", { hasText: "Total records" });
  await chartCard.getByRole("button", { name: /Requirements/ }).click();
  await page.waitForURL(/\/requirements(?:\?.*)?$/);
});

test("dashboard status chart segment navigates to the requirements list filtered to that status", async ({ page }) => {
  await loginAsDemoAdminAndOpenProject(page);

  // Click the first legend row under the "Requirements by status" chart.
  const chartCard = page.locator(".card", { hasText: "Requirements by status" });
  const firstSegmentButton = chartCard.getByRole("button").first();
  const segmentLabel = (await firstSegmentButton.textContent())?.trim();
  await firstSegmentButton.click();

  // The `?status=` param stays in the URL: the list's filters live there, so the filter state is the
  // Status select's value and the URL carries the same status.
  await page.waitForURL(/\/requirements(?:\?.*)?$/);
  const statusSelect = page.getByLabel("Status", { exact: true });
  await expect(statusSelect).not.toHaveValue("");
  // The requirements list's status option text should match the clicked segment's label.
  const selectedOptionText = await statusSelect.locator("option:checked").textContent();
  expect(selectedOptionText?.trim()).toBe(segmentLabel);
});

test("dashboard change-request tile navigates to the change requests list filtered to that status", async ({ page }) => {
  await loginAsDemoAdminAndOpenProject(page);

  const tiles = page.locator(".overview-grid");
  await tiles.getByRole("link", { name: "Change requests approved" }).click();
  // The status stays in the URL as the list's own filter state, as above.
  await page.waitForURL(/\/change-requests(?:\?.*)?$/);
  await expect(page.getByLabel("Status", { exact: true })).toHaveValue("approved");
});

/**
 * Pins that the rendered list matches the filter dropdown after a dashboard glance-tile navigation. The filter is
 * seeded from the URL on first render, so only one filtered requirements fetch is issued; a second, unfiltered fetch
 * would resolve last and overwrite the filtered list. The unfiltered request is delayed here so such a race would fail
 * reliably, and the delayed route never matches while the filter is seeded directly.
 *
 * Navigates via the "Requirements by status" pie-chart's first legend segment, as the sibling test does, rather than
 * the "% Completed" tile: Solstice Cloud Platform's seeded mix (`CLOUD_REQUIREMENTS`, `seed_demo_data.py`) has no
 * `completed` requirements, and the chart lists only non-empty statuses, so its first segment is never empty.
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

  // The status is part of the list's URL, so the landing pattern allows a query string.
  await page.waitForURL(/\/requirements(?:\?.*)?$/);
  const statusSelect = page.getByLabel("Status", { exact: true });
  await expect(statusSelect).not.toHaveValue("");
  const selectedOptionText = await statusSelect.locator("option:checked").textContent();
  expect(selectedOptionText?.trim()).toBe(segmentLabel);

  // The regression itself: not just the dropdown, but the rendered list
  // and the persistent result count must already reflect the filter on first paint. Scoped
  // to the main list column (`.list-page__content`), not the
  // FilterPanel sidebar, so the Status `<select>`'s own matching `<option>`
  // text can't false-match.
  const mainColumn = page.locator(".list-page__content");
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
