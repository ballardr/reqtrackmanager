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
