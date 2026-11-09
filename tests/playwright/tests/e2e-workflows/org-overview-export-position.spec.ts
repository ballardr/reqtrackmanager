import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS } from "./helpers";

/**
 * On the organisation overview, a section's Export trigger sits in the title row's action group beside Reports,
 * level with the Organisation settings link, and does not move when switching between sections.
 */
test("Export stays level with the title row's actions on every organisation compliance page", async ({ page }) => {
  await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
  await page.goto("/org-overview");
  await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
  await expect(page.getByRole("heading", { name: ORG_NAMES.alpha })).toBeVisible();

  const positions: { left: number; top: number }[] = [];
  for (const section of ["Compliance by standard", "Outstanding compliance items"]) {
    await page.locator(".resource-menu-nav").getByRole("link", { name: section, exact: true }).click();
    const exportButton = page.getByRole("button", { name: "Export", exact: true });
    await expect(exportButton).toBeVisible();
    const settings = await page.getByRole("main").getByRole("link", { name: "Organisation settings" }).boundingBox();
    const exported = await exportButton.boundingBox();
    expect(settings && exported).toBeTruthy();
    // The same row as the settings link (and so as Reports), to the left of it.
    expect(Math.abs(exported!.y - settings!.y)).toBeLessThan(12);
    expect(exported!.x).toBeLessThan(settings!.x);
    positions.push({ left: Math.round(exported!.x), top: Math.round(exported!.y) });
  }
  // Switching sections does not move the button.
  expect(positions[1].top).toBe(positions[0].top);
  expect(Math.abs(positions[1].left - positions[0].left)).toBeLessThan(2);
});
