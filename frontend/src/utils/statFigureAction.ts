/**
 * Module: utils/statFigureAction
 *
 * What a stat figure can do when clicked, shared by `StatBar`, `StatGroups`
 * and `StatFigureLabel`: go to a page (`to`), act in place (`onActivate`),
 * and say where it leads in a tooltip (`hint`). Neither `to` nor `onActivate`
 * means a plain, non-interactive number.
 */
export interface StatFigureAction {
  to?: string;
  onActivate?: () => void;
  /** One line shown in a tooltip on hover/focus saying where the figure leads. */
  hint?: string;
}

/**
 * @param action The figure's action.
 * @returns Whether the figure is interactive (so its cell should carry `.stat-linked`).
 */
export function isInteractive(action: StatFigureAction): boolean {
  return Boolean(action.to || action.onActivate);
}
