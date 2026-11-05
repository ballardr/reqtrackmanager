import type { Page } from "@playwright/test";

/**
 * Opens every folded axis block in a scoring editor's Levels section. Each axis folds to "<axis> N levels" until
 * opened (`ScoringAxisLevels`), so a spec that reads or edits a level opens the blocks first. Safe to call when
 * none are folded.
 */
export async function expandScoringLevels(page: Page): Promise<void> {
  // The editor shows a spinner until the scheme has loaded, so wait for its Levels block first.
  await page.getByRole("heading", { name: "Levels", exact: true }).waitFor();
  const folded = page.locator("[role=button][aria-expanded=false]").filter({ hasText: /\d+ levels/ });
  while ((await folded.count()) > 0) await folded.first().click();
}
