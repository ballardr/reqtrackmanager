import { expect, type Locator, type Page } from "@playwright/test";

/**
 * Selects an option in a `LabeledSelect` (`components/LabeledSelect.tsx`).
 *
 * `page.getByLabel(label)` does not reliably resolve: `LabeledSelect` wraps its `<select>` in a `<label>` and
 * Playwright's exact `internal:label=` match includes every `<option>`'s text (as for `FilterField`, see
 * `modules/compliance/helpers.ts`'s `selectFilterOption`), so this locates the label's `<span>` by exact text
 * and walks to the sibling `<select>`.
 *
 * `scope` (a `Page` or `Locator`, e.g. an open dialog) limits the search when `label` could match several
 * controls. Waits for `optionLabel` to be present before selecting: some selects fill from an async fetch and
 * `Locator.selectOption` does not retry waiting for an `<option>`.
 */
export async function selectLabeledOption(scope: Page | Locator, label: string, optionLabel: string): Promise<void> {
  const select = scope.getByText(label, { exact: true }).locator("xpath=following-sibling::select");
  await expect(select).toContainText(optionLabel);
  await select.selectOption({ label: optionLabel });
}
