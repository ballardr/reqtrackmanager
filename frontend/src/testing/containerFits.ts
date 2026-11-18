/**
 * Module: testing/containerFits
 *
 * The shared "does everything in a container fit its width?" assertion. A control group wider than the card, popover or
 * panel that holds it runs out of it and is cut off at the edge; this reads the rendered boxes and returns what sticks out,
 * so Storybook play functions fail instead of someone spotting it in a screenshot. `popoverFit` builds on it for popovers.
 *
 * Rules:
 * - the container does not scroll horizontally;
 * - no visible element inside it, outside a region that deliberately clips or scrolls (an `overflow` other than visible),
 *   extends past the container's left or right edge.
 */
import { expect } from "storybook/test";

/** Pixels of rounding a measurement may differ by without counting as a fault. */
export const TOLERANCE_PX = 1.5;

/** Whether an element scrolls or clips its own content, so what lies beyond its box is not a fault of the container. */
function clipsContent(el: HTMLElement): boolean {
  const style = getComputedStyle(el);
  return style.overflowX !== "visible" || style.overflowY !== "visible";
}

/**
 * Lists what runs out of a container sideways.
 *
 * @param container The card, bubble or panel to check.
 * @param name What to call the container in a fault line.
 * @returns Human-readable faults; empty when everything fits.
 */
export function sidewaysOverflow(container: HTMLElement, name = "container"): string[] {
  const faults: string[] = [];
  const box = container.getBoundingClientRect();
  if (container.scrollWidth > container.clientWidth + TOLERANCE_PX) {
    faults.push(`${name} scrolls sideways (${container.scrollWidth} of ${container.clientWidth})`);
  }
  for (const el of Array.from(container.querySelectorAll<HTMLElement>("*"))) {
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0 || getComputedStyle(el).visibility === "hidden") continue;
    let clipped = false;
    for (let up = el.parentElement; up && up !== container; up = up.parentElement) {
      if (clipsContent(up)) { clipped = true; break; }
    }
    if (clipped) continue;
    if (rect.left < box.left - TOLERANCE_PX || rect.right > box.right + TOLERANCE_PX) {
      const label = el.getAttribute("aria-label") ?? el.getAttribute("role") ?? el.tagName.toLowerCase();
      faults.push(`${label} ${Math.round(rect.left)}..${Math.round(rect.right)} sticks out of the ${name} ${Math.round(box.left)}..${Math.round(box.right)}`);
    }
  }
  return faults;
}

/**
 * Asserts that nothing in a container runs out of it sideways.
 *
 * @param container The card, bubble or panel to check.
 * @param name What to call the container in a fault line.
 */
export async function expectContainerFits(container: HTMLElement, name = "container"): Promise<void> {
  await expect(sidewaysOverflow(container, name)).toEqual([]);
}
