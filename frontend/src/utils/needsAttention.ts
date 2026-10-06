/**
 * Module: utils/needsAttention
 *
 * Whether a stat figure currently "needs attention": it is flagged `gap`
 * (a problem to fix when non-zero) and its value is a non-zero number.
 * Shared by `StatBar` and `StatGroups` so both flag figures identically.
 *
 * @param figure The figure's value and whether it is a gap measure.
 * @returns True for a non-zero gap figure.
 */
export function needsAttention(figure: { value: string | number; gap?: boolean }): boolean {
  return figure.gap === true && Number(figure.value) > 0;
}
