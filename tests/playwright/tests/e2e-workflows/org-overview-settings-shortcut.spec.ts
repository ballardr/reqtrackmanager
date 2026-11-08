import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS } from "./helpers";

/**
 * The organisation overview carries a "settings" icon link beside the title that opens the organisation admin
 * page. It is shown to every member who can see the overview, because the admin page loads for every member
 * and gates its own settings sections by role.
 */
for (const [label, persona] of [
  ["an organisation administrator", PERSONAS.orgAdminAlphaBeta],
  ["a plain member", PERSONAS.memberAlphaBeta],
] as const) {
  test(`${label} opens organisation admin from the overview settings shortcut`, async ({ page }) => {
    await loginAs(page, persona.email);
    await page.goto("/org-overview");
    await page.getByRole("link", { name: ORG_NAMES.alpha }).click();
    await expect(page.getByRole("heading", { name: ORG_NAMES.alpha })).toBeVisible();

    await page.getByRole("link", { name: "Organisation settings" }).click();
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin/);
  });
}
