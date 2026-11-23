/**
 * Module: testing/popoverFit
 *
 * The shared "does a popover's content fit its bubble, and the bubble its
 * window?" assertion: reads the rendered boxes and returns what is wrong, for
 * Storybook play functions. Rules: the bubble lies inside the window; nothing
 * in it sticks out sideways (`sidewaysOverflow`); when a trigger is given, the
 * bubble does not cover it.
 */
import { expect } from "storybook/test";

import { sidewaysOverflow, TOLERANCE_PX } from "./containerFits";

/**
 * Lists how a popover bubble fails to fit.
 *
 * @param bubble The popover's bubble (`role="dialog"` in the document body).
 * @param trigger The element the popover opened from; when given, the bubble must not cover it.
 * @returns Human-readable faults; empty when the bubble fits its window and holds all its content.
 */
export function popoverFitViolations(bubble: HTMLElement, trigger?: HTMLElement): string[] {
  const faults: string[] = [];
  const box = bubble.getBoundingClientRect();
  const round = (n: number) => Math.round(n);

  if (box.left < -TOLERANCE_PX || box.right > window.innerWidth + TOLERANCE_PX) {
    faults.push(`bubble ${round(box.left)}..${round(box.right)} is outside the window width ${window.innerWidth}`);
  }
  if (box.top < -TOLERANCE_PX || box.bottom > window.innerHeight + TOLERANCE_PX) {
    faults.push(`bubble ${round(box.top)}..${round(box.bottom)} is outside the window height ${window.innerHeight}`);
  }
  faults.push(...sidewaysOverflow(bubble, "bubble"));

  if (trigger) {
    const t = trigger.getBoundingClientRect();
    const overlaps = box.left < t.right && box.right > t.left && box.top < t.bottom && box.bottom > t.top;
    if (overlaps) faults.push("bubble covers its trigger");
  }
  return faults;
}

/**
 * Asserts that a popover bubble fits (see `popoverFitViolations`).
 *
 * @param bubble The popover's bubble.
 * @param trigger The element the popover opened from, when it must stay uncovered.
 */
export async function expectPopoverFits(bubble: HTMLElement, trigger?: HTMLElement): Promise<void> {
  await expect(popoverFitViolations(bubble, trigger)).toEqual([]);
}
