import { expect, type Page } from "@playwright/test";

/**
 * Creates a compliance standard together with its mandatory first (draft)
 * version, via the top-level `/standards` page's "New standard" dialog
 * ("Compliance Standards" as a
 * first-class, cross-org, project-like nav entity). Every compliance spec
 * in this directory that needs a fixture standard now goes through this
 * one-step flow instead of the former `selectOrgAdminGroup(page,
 * "Compliance")` + org-admin "Standards" tab setup they used to share —
 * that org-admin group no longer exists (`ComplianceAdminPanel.tsx` is
 * fully retired).
 *
 * Selects `orgName` in the dialog's own organisation picker only when it's
 * actually rendered — `StandardFormModal.tsx` hides that field entirely
 * for a caller who can only create standards in one organisation, matching
 * `ProjectListPage.tsx`'s own "New project" org picker precedent.
 *
 * Leaves the browser on the new standard's own `/standards/:standardId`
 * workspace (Overview section) — creating always navigates straight there.
 */
export async function createStandardWithVersion(
  page: Page,
  { orgName, reference, name, versionLabel = "v1.0" }: { orgName: string; reference: string; name: string; versionLabel?: string }
): Promise<void> {
  await page.goto("/standards");
  await page.getByRole("button", { name: "New standard" }).click();
  const dialog = page.getByRole("dialog", { name: "New standard" });
  // A `combobox` role, not a bare `getByLabel("Organisation")` — the
  // latter is a case-insensitive substring match that also matches the
  // "Issuing organisation" text input further down this same form (a real
  // bug this comment's own predecessor had for a single-org caller, found
  // and fixed while adding a spec against `orgAdminGamma`
  // — Gamma-only, so the real "Organisation" `<select>` never renders at
  // all here and `getByLabel` silently resolved to that other input
  // instead). Restricting to `combobox` excludes the text input outright,
  // regardless of name overlap.
  const orgPicker = dialog.getByRole("combobox", { name: "Organisation" });
  if ((await orgPicker.count()) > 0) {
    await orgPicker.selectOption({ label: orgName });
  }
  await dialog.getByLabel("Standard reference").fill(reference);
  await dialog.getByLabel("Standard name").fill(name);
  await dialog.getByLabel("Initial version label").fill(versionLabel);
  await dialog.getByRole("button", { name: "Save" }).click();

  await expect(page).toHaveURL(/\/standards\/[0-9a-f-]+$/);
  await expect(page.getByRole("heading", { name: new RegExp(`${reference} — ${name}`) })).toBeVisible();
}

/**
 * Selects an option in one of the filter panel's `FilterSelect`s (e.g. the Outstanding panels' Standard/Standard
 * version/Sub-section filters), found by its accessible name.
 *
 * @param page The page showing the filter panel.
 * @param fieldLabel The filter's caption, matched exactly.
 * @param optionLabel The visible text of the option to choose.
 */
export async function selectFilterOption(page: Page, fieldLabel: string, optionLabel: string): Promise<void> {
  // `FilterSelect` names its `<select>` with the caption (aria-label), and the caption's `(?)` button sits between the
  // caption and the select, so the select is found by its accessible name rather than as the caption's sibling.
  await page.getByRole("combobox", { name: fieldLabel, exact: true }).selectOption({ label: optionLabel });
}
