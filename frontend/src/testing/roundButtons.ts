/**
 * Module: testing/roundButtons
 *
 * The shared "is every round icon button a circle?" assertion. A round button is
 * `.btn-round` (style guide "Pattern: button sizes"); `border-radius: 50%` draws
 * a circle only when the rendered box is square, which a base `.btn` rule (such
 * as `min-height`) can break. This reads the box and radius of every `.btn-round`
 * and returns what is wrong, for Storybook play functions and Playwright specs.
 * Self-contained (no imports, helpers inside the function) so Playwright can
 * ship it with `page.evaluate`, like `iconSizeGeometry`.
 */

/** One `.btn-round` as drawn: its box and the computed corner radius. */
export interface RoundButtonMeasurement {
  /** The button's accessible name, to locate it. */
  name: string;
  widthPx: number;
  heightPx: number;
  /** Computed `border-top-left-radius`, for example "14px" or "50%". */
  radius: string;
}

/** What `roundButtonGeometry` reports. */
export interface RoundButtonGeometry {
  measurements: RoundButtonMeasurement[];
  violations: string[];
}

/**
 * Measures every `.btn-round` under `root` and reports the ones that are not circles.
 *
 * @param root Element to search; defaults to the whole document.
 * @returns Every measurement and the violations: a box whose width and height differ by more than half a
 * pixel, or a radius that is less than half the box.
 */
export function roundButtonGeometry(root?: Element): RoundButtonGeometry {
  const scope: ParentNode = root ?? document;
  const measurements: RoundButtonMeasurement[] = [];
  const violations: string[] = [];
  scope.querySelectorAll<HTMLElement>(".btn-round").forEach((button) => {
    const box = button.getBoundingClientRect();
    if (box.width === 0 && box.height === 0) return; // not drawn (a hidden panel)
    const radius = getComputedStyle(button).borderTopLeftRadius;
    const name = button.getAttribute("aria-label") ?? button.textContent?.trim() ?? "(unnamed)";
    measurements.push({ name, widthPx: box.width, heightPx: box.height, radius });
    if (Math.abs(box.width - box.height) > 0.5) {
      violations.push(`${name}: ${box.width}x${box.height}px is not square`);
    }
    // A percentage radius is reported as such; a pixel one (the browser resolving 50%) must reach half the side.
    const resolved = radius.endsWith("%") ? (parseFloat(radius) / 100) * box.width : parseFloat(radius);
    if (!(resolved >= Math.min(box.width, box.height) / 2 - 0.5)) {
      violations.push(`${name}: corner radius ${radius} does not make a circle of ${box.width}px`);
    }
  });
  return { measurements, violations };
}

/** Violations only, for Storybook play functions. */
export function roundButtonViolations(root?: Element): string[] {
  return roundButtonGeometry(root).violations;
}
