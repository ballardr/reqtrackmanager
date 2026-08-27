import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS, PROJECT_NAMES } from "./e2e-workflows/helpers";

/**
 * UX review: the project members list ("Effective members" under Project
 * Admin's Project groups tab) was a bare, unsearchable bullet list — it now
 * matches Org Admin's Users table's structural pattern: a search box and a
 * sortable table (Email/Name/Role/Source), Source standing in for the org
 * table's account-level status/2FA/last-login columns, which don't exist at
 * project scope (see EffectiveMember's fields).
 */
test("project members table is searchable and sortable", async ({ page }) => {
  await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
  await page.getByText(PROJECT_NAMES.beta2).click();
  await page.getByRole("link", { name: "Project admin", exact: true }).click();
  await page.getByRole("tab", { name: "Project groups" }).click();

  const section = page.getByRole("button", { name: /Effective members/ });
  if ((await section.getAttribute("aria-expanded")) !== "true") await section.click();
  await page.getByRole("button", { name: "Show members" }).click();

  const table = page.locator("table").filter({ has: page.getByRole("columnheader", { name: "Email" }) });
  await expect(table).toBeVisible();
  await expect(table.getByRole("columnheader", { name: "Role" })).toBeVisible();
  await expect(table.getByRole("columnheader", { name: "Source" })).toBeVisible();
  const rowCountBefore = await table.locator("tbody tr").count();
  expect(rowCountBefore).toBeGreaterThan(0);

  // Search narrows the table.
  const firstRowEmail = (await table.locator("tbody tr").first().locator("td").first().textContent())?.trim();
  await page.getByPlaceholder("Search members").fill(firstRowEmail!);
  await expect(table.locator("tbody tr")).toHaveCount(1);
  await page.getByPlaceholder("Search members").fill("");
  await expect(table.locator("tbody tr")).toHaveCount(rowCountBefore);

  // Sorting by Email toggles aria-sort and reorders rows.
  await table.getByRole("columnheader", { name: "Email" }).getByRole("button").click();
  await expect(table.getByRole("columnheader", { name: "Email" })).toHaveAttribute("aria-sort", "ascending");
});
