import { expect, type Locator, type Page } from "@playwright/test";

/**
 * Selects an option in a `LabeledSelect` (`components/LabeledSelect.tsx`) —
 * `page.getByLabel(label)` doesn't reliably resolve here: `LabeledSelect`
 * renders `<label class="stack"><span>{label}</span><select aria-label=
 * {label}>...</select></label>`, a `<label>` that *wraps* its control
 * rather than pointing at it via `for`/`id`, and Playwright's own
 * `internal:label=` selector engine matches against the label element's
 * full `textContent` for an exact match — which, for a wrapped `<select>`,
 * includes every one of its `<option>` elements' own text too. This is the
 * exact same quirk `modules/compliance/helpers.ts`'s own `selectFilterOption`
 * documents and works around for `FilterField` (`components/FilterPanel
 * .tsx`) — `LabeledSelect` wraps its control in an identically-shaped
 * `<label><span>...</span><select>...</select></label>`, so the same
 * work-around applies: locate the label's own `<span>` by its *exact* text
 * (no other descendants to pollute its `textContent`) and walk to the
 * sibling `<select>` rather than trusting label association at all.
 *
 * `scope` (a `Page` or a narrower `Locator`, e.g. an open dialog) lets a
 * caller scope the search when the same `label` text could otherwise match
 * more than one control on the page at once (`DecisionRelationshipsSection`
 * .tsx`'s own "Decision"/"Requirement" target picker changes label text
 * depending on the selected relationship kind, but "Relationship" itself is
 * always present once the section has rendered).
 *
 * Waits for `optionLabel` to actually be present among the select's options
 * before selecting — several of this module's own selects populate their
 * options from an async fetch triggered by an earlier interaction in the
 * same test (e.g. changing "Relationship" to "Supersedes another Decision"
 * triggers a `listDecisions` call before the "Decision this supersedes"
 * select has anything to choose from yet), and `Locator.selectOption`
 * itself does not retry waiting for a specific `<option>` to appear.
 */
export async function selectLabeledOption(scope: Page | Locator, label: string, optionLabel: string): Promise<void> {
  const select = scope.getByText(label, { exact: true }).locator("xpath=following-sibling::select");
  await expect(select).toContainText(optionLabel);
  await select.selectOption({ label: optionLabel });
}
