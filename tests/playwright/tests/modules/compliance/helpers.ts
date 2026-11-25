import { expect, type Page } from "@playwright/test";

import { openProject } from "../../e2e-workflows/helpers";

/**
 * Creates a compliance standard together with its mandatory first (draft) version, through the `/standards`
 * page's "New standard" dialog. Every compliance spec that needs a fixture standard uses this one-step flow.
 *
 * Selects `orgName` in the dialog's organisation picker only when it is rendered: `StandardFormModal.tsx` hides
 * that field for a caller who can create standards in one organisation only (as `ProjectListPage.tsx`'s
 * "New project" org picker does).
 *
 * Leaves the browser on the new standard's `/standards/:standardId` workspace (Overview section).
 */
export async function createStandardWithVersion(
  page: Page,
  { orgName, reference, name, versionLabel = "v1.0" }: { orgName: string; reference: string; name: string; versionLabel?: string }
): Promise<void> {
  await page.goto("/standards");
  await page.getByRole("button", { name: "New standard" }).click();
  const dialog = page.getByRole("dialog", { name: "New standard" });
  // A `combobox` role, not a bare `getByLabel("Organisation")`: the latter is a case-insensitive substring
  // match that also matches the "Issuing organisation" text input. For a single-org caller the
  // "Organisation" `<select>` never renders, so `getByLabel` would resolve to that other input.
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
 * Publishes the open standard's first version (with one requirement, which publishing needs) and assigns it to a
 * project, so the organisation-wide status tabs have a row of this spec's own to read instead of relying on
 * assignments another spec left behind.
 *
 * Call it straight after `createStandardWithVersion` (the browser is on the standard's workspace).
 */
export async function publishAndAssignStandard(
  page: Page,
  { reference, name, projectName, versionLabel = "v1.0" }: { reference: string; name: string; projectName: string; versionLabel?: string }
): Promise<void> {
  await page.getByRole("link", { name: "Versions", exact: true }).click();
  await page.getByRole("button", { name: versionLabel }).click();
  await page.getByRole("button", { name: "Add requirement" }).click();
  await page.getByLabel("Requirement name").fill(`${name} requirement`);
  await page.getByRole("dialog", { name: "New requirement" }).getByRole("button", { name: "Save" }).click();
  await expect(page.getByText(`${name} requirement`)).toBeVisible();
  await page.getByRole("button", { name: "Publish" }).click();
  await page.getByRole("dialog", { name: "Publish this version?" }).getByRole("button", { name: "Publish" }).click();
  await expect(page.getByText("Version published.")).toBeVisible();

  await openProject(page, projectName);
  await page.getByRole("link", { name: "Compliance", exact: true }).click();
  await page.getByRole("button", { name: "Assign standard" }).click();
  const dialog = page.getByRole("dialog", { name: "Assign compliance standard" });
  await dialog.getByLabel("Standard", { exact: true }).selectOption({ label: `${reference} — ${name}` });
  await dialog.getByLabel("Standard version").selectOption({ label: versionLabel });
  await dialog.getByRole("button", { name: "Assign" }).click();
  await expect(page.getByText(new RegExp(reference))).toBeVisible();
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

/**
 * Opens one of the Standards page's organisation-wide status tabs (By standard, Outstanding) for an organisation, from
 * the Standards page, as a person reaches it. The Organisation filter is present only for a person who may read
 * the status of more than one organisation, so it is used when it is there.
 *
 * @param page The page.
 * @param tab The tab's label.
 * @param orgName The organisation whose status to show.
 */
export async function openComplianceStatusTab(page: Page, tab: "By standard" | "Outstanding", orgName: string): Promise<void> {
  await page.goto("/standards");
  await page.getByRole("tab", { name: tab, exact: true }).click();
  await expect(page.getByRole("tab", { name: tab, exact: true })).toHaveAttribute("aria-selected", "true");
  // The page draws its heading once the organisations are known, so the filter (if any) is there by then.
  await expect(page.getByRole("heading", { name: "Compliance Standards" })).toBeVisible();
  const organisation = page.getByRole("combobox", { name: "Organisation", exact: true });
  if (await organisation.count()) await organisation.selectOption({ label: orgName });
}
