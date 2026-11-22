/**
 * Module: testing/stressFixtures
 *
 * The story harness for "long text never breaks the layout" (`gridStability`). A grid or table story that
 * calls `TextStress` renders its view twice at the same width, once with short text and once with a 200
 * character name, a 60 character word with no space and a long code in several rows, and
 * `expectStressStable` then asserts the long render keeps the shape of the short one (columns, controls and
 * edges). A new grid or table view is covered by one `LongText` story that takes `short`/`long` fixtures.
 *
 * Responsibilities:
 * - `STRESS_TEXT` / `stressText`: the shared long fixtures, so every view is stressed the same way.
 * - `expectStressStable`: the play-function assertion (rules 1 to 4 of `gridStability`).
 *
 * Dependencies: `testing/gridStability`, `storybook/test`. The view itself is `TextStress` (`testing/TextStress.tsx`), a separate
 * file so each exports only components or only functions.
 */
import { expect } from "storybook/test";

import { layoutChanges, gridLayout } from "./gridStability";

/** The long values every view is stressed with. */
export const STRESS_TEXT = {
  /** A 200 character name made of ordinary words, so it can wrap where a cell allows it. */
  name: "An exceptionally long name that keeps going well past any sensible single line of text so that every control and "
    + "column beside it is put under real pressure to stay where it belongs and not move at all",
  /** A 60 character word with no space or break opportunity. */
  word: "Supercalifragilisticexpialidocious_Supercalifragilisticexpial",
  /** A long code, such as an organisation-qualified record code. */
  code: "ACME-ENGINEERING-PLATFORM-REQ-000123",
  /** A long summary line, such as a vocabulary row's description. */
  summary: "Software · Solid, one-way, default protocol HTTPS, JSON · Under Software interface and every other system it touches",
};

/**
 * Returns the long fixture in the stressed render and the short one otherwise.
 *
 * @param long Whether this is the long-text render (the argument `TextStress` passes to `render`).
 * @param short The short text.
 * @param key Which long fixture to use (default `name`).
 */
export function stressText(long: boolean, short: string, key: keyof typeof STRESS_TEXT = "name"): string {
  return long ? STRESS_TEXT[key] : short;
}

/**
 * Asserts that the long-text render of a `TextStress` keeps the layout of the short one: no grid breaks any
 * of rules 1 to 3 in either render, and the column widths of a fixed-column grid are the same in both.
 *
 * @param canvasElement The story's canvas element (the play function's `canvasElement`).
 */
export async function expectStressStable(canvasElement: HTMLElement): Promise<void> {
  const short = canvasElement.querySelector<HTMLElement>('[data-stress="short"]');
  const long = canvasElement.querySelector<HTMLElement>('[data-stress="long"]');
  if (!short || !long) throw new Error("expectStressStable needs a story rendered with TextStress");
  const before = gridLayout(short);
  const after = gridLayout(long);
  if (before.grids.length === 0 && before.rowsChecked === 0) throw new Error("the story drew no grid, table or row layout, so nothing was checked");
  await expect(before.violations, "short text").toEqual([]);
  await expect(after.violations, "long text").toEqual([]);
  await expect(layoutChanges(before.grids, after.grids)).toEqual([]);
}
