import { expect, test, type Page } from "@playwright/test";

import { installCleanupHook } from "./helpers";
import { setUpOrg } from "../modules/stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * The nav rail's links start level with the top of the rail, beside the collapse toggle (not below
 * it), and neither a link nor the scrollbar strip runs under the toggle, expanded or icon-only.
 * Measured from the rendered boxes, so a stylesheet change that moves either is caught. Each test signs in as
 * its own disposable administrator: collapsing the rail is a stored per-user preference, so doing it to a
 * shared persona would leave every later spec of that persona with an icon-only rail.
 */
async function measure(page: Page) {
  const toggle = await page.getByRole("button", { name: /Collapse navigation|Expand navigation/ }).boundingBox();
  const links = page.getByRole("navigation").getByRole("link");
  // The first item of the list (a section label or a link) is what must be level with the toggle.
  const first = await page.locator(".nav-rail-scroll > :first-child").first().boundingBox();
  const boxes = await links.evaluateAll((els) => els.map((e) => {
    const r = e.getBoundingClientRect();
    return { x: r.x, y: r.y, right: r.right, bottom: r.bottom, height: r.height };
  }));
  const scroll = await page.locator(".nav-rail-scroll").boundingBox();
  const rail = await page.getByRole("navigation").boundingBox();
  return { toggle: toggle!, first: first!, boxes, scroll: scroll!, rail: rail! };
}

for (const collapsed of [false, true]) {
  test(`nav rail ${collapsed ? "icon-only" : "expanded"}: links start at the top and clear the collapse toggle`, async ({ page }) => {
    await setUpOrg(page, collapsed ? "RailIcons" : "RailWide");
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/");
    if (collapsed) await page.getByRole("button", { name: "Collapse navigation" }).click();
    const toggle = page.getByRole("button", { name: collapsed ? "Expand navigation" : "Collapse navigation" });
    await expect(toggle).toBeVisible();
    await expect.poll(async () => (await measure(page)).rail.width).toBe(collapsed ? 56 : 220);

    const { toggle: t, first, boxes, scroll, rail } = await measure(page);
    // The first item's top is within the toggle's vertical extent, i.e. level with it, not below it.
    expect(first.y).toBeGreaterThanOrEqual(t.y - 1);
    expect(first.y).toBeLessThanOrEqual(t.y + t.height);
    // No link overlaps the toggle's box.
    for (const b of boxes) {
      const overlaps = b.x < t.x + t.width && b.right > t.x && b.y < t.y + t.height && b.bottom > t.y;
      expect(overlaps, `a nav link at ${b.x},${b.y} intersects the collapse toggle`).toBe(false);
    }
    // The scroll container (and so its scrollbar) ends before the toggle starts.
    expect(scroll.x + scroll.width).toBeLessThanOrEqual(t.x + 1);
    // And the list begins at the rail's top edge, with no dead band above it.
    expect(scroll.y).toBeLessThanOrEqual(rail.y + 1);
  });
}
