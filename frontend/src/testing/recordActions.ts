/**
 * Module: testing/recordActions
 *
 * Storybook `play` helpers for the object-action menu in `RecordHeader`, so stories
 * of detail pages drive Archive / Delete permanently / Subscribe the way a user does
 * (open "{Record} actions", pick an item) without repeating the menu plumbing.
 *
 * External dependencies: `storybook/test`.
 */
import { userEvent, within } from "storybook/test";

type Canvas = ReturnType<typeof within>;

const menuLabel = (recordLabel: string) => `${recordLabel} actions`;

/**
 * Opens a record's object-action menu.
 *
 * @param canvas The story canvas.
 * @param recordLabel Singular record name used by the page ("Persona", "Stakeholder Need").
 * @returns Queries scoped to the opened menu.
 */
export async function openRecordActions(canvas: Canvas, recordLabel: string) {
  await userEvent.click(canvas.getByRole("button", { name: menuLabel(recordLabel) }));
  return within(within(document.body).getByRole("menu", { name: menuLabel(recordLabel) }));
}

/** Opens the menu and clicks the item named `item`. */
export async function chooseRecordAction(canvas: Canvas, recordLabel: string, item: string) {
  const menu = await openRecordActions(canvas, recordLabel);
  await userEvent.click(menu.getByRole("menuitem", { name: item }));
}

/**
 * Names of the menu's items, or `[]` when the page draws no menu (the user has no object
 * actions). Closes the menu again so the story can carry on.
 */
export async function recordActionNames(canvas: Canvas, recordLabel: string): Promise<string[]> {
  if (!canvas.queryByRole("button", { name: menuLabel(recordLabel) })) return [];
  const menu = await openRecordActions(canvas, recordLabel);
  const names = menu.getAllByRole("menuitem").map((el) => el.textContent?.trim() ?? "");
  await userEvent.keyboard("{Escape}");
  return names;
}
