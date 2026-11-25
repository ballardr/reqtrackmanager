import { expect, test } from "@playwright/test";

import { installCleanupHook, loginAs, ORG_NAMES, PERSONAS } from "../../e2e-workflows/helpers";
import { createStandardWithVersion } from "./helpers";

/**
 * Job to be done: a Compliance standard's tile reads and looks like a project's tile — the title is the link
 * and the cards share one look (the shared `TileCard`).
 *
 * The spec creates its own uniquely-named standard, so it passes alone, repeated or out of order.
 */
test.describe("Compliance Module: standard tiles share the project card's look", () => {
  installCleanupHook();

  test("a standard opens from its title, and its card is styled as a project card", async ({ page }) => {
    const suffix = Date.now();
    const name = `E2E Tile Standard ${suffix}`;
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await createStandardWithVersion(page, { orgName: ORG_NAMES.alpha, reference: `TILE-${suffix}`, name });

    await page.goto("/standards");
    await page.getByRole("button", { name: "Tile view" }).click();
    const card = page.locator(".tile-card", { has: page.getByRole("link", { name, exact: true }) });
    const title = card.getByRole("link", { name, exact: true });
    await expect(title).toBeVisible();
    // The title reads as a link: not the body-text colour, and only the title is a link (the card is not).
    const colours = await title.evaluate((el) => ({ link: getComputedStyle(el).color, text: getComputedStyle(el.parentElement!).color }));
    expect(colours.link).not.toBe(colours.text);
    await expect(card.getByRole("link")).toHaveCount(1);
    const standardCard = await card.evaluate((el) => {
      const s = getComputedStyle(el);
      return { radius: s.borderRadius, shadow: s.boxShadow, border: s.borderTopWidth };
    });

    await page.getByRole("link", { name: "Projects", exact: true }).first().click();
    await page.getByRole("button", { name: "Tile view" }).click();
    const projectCard = page.locator(".tile-card").first();
    await expect(projectCard).toBeVisible();
    const projectStyle = await projectCard.evaluate((el) => {
      const s = getComputedStyle(el);
      return { radius: s.borderRadius, shadow: s.boxShadow, border: s.borderTopWidth };
    });
    expect(projectStyle).toEqual(standardCard);

    await page.goto("/standards");
    await page.getByRole("link", { name, exact: true }).click();
    await expect(page).toHaveURL(/\/standards\/[0-9a-f-]+$/);
    await expect(page.getByRole("heading", { name: new RegExp(name) })).toBeVisible();
  });
});
