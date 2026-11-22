/**
 * Module: testing/tooltips
 *
 * Story helpers for asserting the shared `Tooltip` (never a native `title`, which the project forbids on a control that
 * opens a list or on a choice inside one).
 */
import { expect, userEvent, within } from "storybook/test";

/**
 * Hovers an element and expects the shared tooltip to say `text`, then moves away so it does not stay over later steps.
 *
 * @param target The element to hover. A disabled input gets no pointer events, so pass its label (`reasonTarget`).
 * @param text The tooltip's text, or a pattern it must match.
 */
export async function expectTooltip(target: HTMLElement, text: string | RegExp): Promise<void> {
  await userEvent.hover(target);
  await expect(await within(document.body).findByRole("tooltip", { hidden: true })).toHaveTextContent(text);
  await userEvent.unhover(target);
}

/**
 * The element to hover for the reason a checkbox is disabled: the label (or row) around it.
 *
 * @param checkbox The disabled checkbox.
 * @returns Its enclosing label.
 */
export function reasonTarget(checkbox: HTMLElement): HTMLElement {
  return checkbox.closest("label") as HTMLElement;
}
