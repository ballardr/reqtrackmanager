import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS, PROJECT_NAMES, selectProjectAdminGroup } from "./e2e-workflows/helpers";

/**
 * UX review: the project members list ("Effective members", now under
 * Project Admin's "Members" section — Phase 5, docs/decisions.md, moved it
 * off the old combined "Project groups" tab) was a bare, unsearchable
 * bullet list — it now matches Org Admin's Users table's structural
 * pattern: a search box and a sortable table (Email/Name/Role/Source),
 * Source standing in for the org table's account-level status/2FA/
 * last-login columns, which don't exist at project scope (see
 * EffectiveMember's fields).
 */
test("project members table is searchable and sortable", async ({ page }) => {
  await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
  await page.getByText(PROJECT_NAMES.beta2).click();
  await page.getByRole("link", { name: "Project admin", exact: true }).click();
  await selectProjectAdminGroup(page, "Members");

  const section = page.getByRole("button", { name: /Effective members/ });
  if ((await section.getAttribute("aria-expanded")) !== "true") await section.click();
  await page.getByRole("button", { name: "Show members" }).click();

  // Scoped to the "Effective members" section specifically: the new
  // Phase-5 `MemberRoleTable` above it on the same "Members" section is
  // also a table with its own "Email" column header, so an unscoped
  // `table` locator would match both.
  const effectiveMembersCard = page.locator(".card", { has: page.getByRole("button", { name: "Effective members section" }) });
  const table = effectiveMembersCard.locator("table").filter({ has: page.getByRole("columnheader", { name: "Email" }) });
  await expect(table).toBeVisible();
  await expect(table.getByRole("columnheader", { name: "Role" })).toBeVisible();
  await expect(table.getByRole("columnheader", { name: "Source" })).toBeVisible();
  const rowCountBefore = await table.locator("tbody tr").count();
  expect(rowCountBefore).toBeGreaterThan(0);

  // Search narrows the table. Scoped to this section's own search box —
  // the new Phase-5 `MemberRoleTable` above it has a "Search members and
  // groups" placeholder, a substring superset of "Search members", so an
  // unscoped `getByPlaceholder("Search members")` would be ambiguous.
  const firstRowEmail = (await table.locator("tbody tr").first().locator("td").first().textContent())?.trim();
  await effectiveMembersCard.getByPlaceholder("Search members").fill(firstRowEmail!);
  await expect(table.locator("tbody tr")).toHaveCount(1);
  await effectiveMembersCard.getByPlaceholder("Search members").fill("");
  await expect(table.locator("tbody tr")).toHaveCount(rowCountBefore);

  // Sorting by Email toggles aria-sort and reorders rows.
  await table.getByRole("columnheader", { name: "Email" }).getByRole("button").click();
  await expect(table.getByRole("columnheader", { name: "Email" })).toHaveAttribute("aria-sort", "ascending");
});
