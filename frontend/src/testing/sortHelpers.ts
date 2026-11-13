/**
 * Module: testing/sortHelpers
 *
 * Story helpers that pin a `DirectoryTable`'s header sort: read what a column shows in row order, click its header and
 * check the order after each click (ascending, then descending). Shared so every list's sort story reads the same way.
 */
import { expect, userEvent, waitFor, within } from "storybook/test";

/** The text of each body row's cell under the column header `header`, in the order the rows are shown. */
export function columnTexts(table: HTMLElement, header: string): string[] {
  const headers = within(table).getAllByRole("columnheader");
  const index = headers.findIndex((th) => (th.textContent ?? "").trim() === header);
  if (index < 0) throw new Error(`No column header "${header}"`);
  return within(table).getAllByRole("row").slice(1).map((row) => (row.querySelectorAll("td")[index]?.textContent ?? "").trim());
}

/**
 * Clicks a sortable column's header twice and checks the column's order after each click: ascending, then descending.
 *
 * @param table The rendered `<table>`.
 * @param header The column header's text (also the sort button's name).
 * @param ascending The column's cell texts, top to bottom, after the first click.
 * @param descending The cell texts after the second click; the reverse of `ascending` when omitted.
 */
export async function expectHeaderSorts(table: HTMLElement, header: string, ascending: string[], descending?: string[]): Promise<void> {
  await userEvent.click(within(table).getByRole("button", { name: header }));
  await waitFor(() => expect(columnTexts(table, header)).toEqual(ascending));
  await userEvent.click(within(table).getByRole("button", { name: header }));
  await waitFor(() => expect(columnTexts(table, header)).toEqual(descending ?? [...ascending].reverse()));
}

/**
 * Clicks a text column's header twice and checks the rows come back ordered by that text, ascending then descending,
 * whatever order the rows started in. For a list whose fixture rows are not worth spelling out; the fixture must hold
 * at least two distinct values in the column, and none empty (an empty value sorts last, which this does not model).
 *
 * @param table The rendered `<table>`.
 * @param header The column header's text (also the sort button's name).
 */
export async function expectHeaderOrdersText(table: HTMLElement, header: string): Promise<void> {
  const texts = columnTexts(table, header);
  expect(new Set(texts).size).toBeGreaterThan(1);
  const ascending = [...texts].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base", numeric: true }));
  await expectHeaderSorts(table, header, ascending);
}
