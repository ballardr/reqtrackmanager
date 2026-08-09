import { expect, test } from "@playwright/test";

/**
 * Clicking a status badge on a list/tile row applies it as a filter (same
 * effect as picking it from the filter panel), and clicking it again
 * clears the filter — verified against the Requirements page using the
 * demo dataset (scripts/seed_demo_data.py), which seeds requirements at
 * varied lifecycle stages so more than one status is guaranteed present.
 */
test("clicking a requirement status badge filters the list, and clicking it again clears the filter", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo.admin@example.com");
  await page.getByLabel("Password").fill("DemoDemo123!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/projects(\/|$)/);

  await page.goto("/projects");
  await page.getByRole("link", { name: "Falcon-3 Inspection Drone" }).click();
  await page.getByRole("link", { name: "Requirements", exact: true }).click();
  await page.getByLabel("List view").click();

  const statusFilterSelect = page.getByLabel("Status");
  await expect(statusFilterSelect).toHaveValue("");

  const rows = page.locator("table tbody tr");
  await expect(rows.first()).toBeVisible();
  const totalCount = await rows.count();
  expect(totalCount).toBeGreaterThan(0);

  const firstBadge = rows.first().locator(".badge").first();
  const badgeText = (await firstBadge.textContent())?.trim();
  expect(badgeText).toBeTruthy();

  await firstBadge.click();
  await expect(statusFilterSelect).not.toHaveValue("");
  await expect(rows.first()).toBeVisible();

  const filteredCount = await rows.count();
  expect(filteredCount).toBeGreaterThan(0);
  expect(filteredCount).toBeLessThanOrEqual(totalCount);
  for (let i = 0; i < filteredCount; i++) {
    await expect(rows.nth(i).locator(".badge").first()).toHaveText(badgeText!);
  }

  // Clicking the same badge again on a still-visible matching row clears the filter.
  await rows.first().locator(".badge").first().click();
  await expect(statusFilterSelect).toHaveValue("");
  await expect(rows.first()).toBeVisible();
  await expect(rows).toHaveCount(totalCount);
});
