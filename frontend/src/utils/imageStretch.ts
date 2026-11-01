/**
 * Module: utils/imageStretch
 *
 * Tells whether an image block's Width and Height, both set, would stretch the picture out of its own shape.
 *
 * Responsibilities:
 * - Turn the block's width and height into one ratio when both are absolute lengths (cm or mm).
 * - Compare it with the picture's pixel ratio and report how far apart they are.
 *
 * Design decisions: a width as a share of the text cannot be compared without the page width, so it is never judged. The
 * result is advice for a warning, never an error: stretching is the author's choice.
 */

/** How far (as a fraction) the ratios may differ before the form says the picture is stretched. */
export const STRETCH_TOLERANCE = 0.05;

/** What the form tells the author about a stretched picture. */
export interface Stretch {
  /** The chosen width divided by the chosen height. */
  chosen: number;
  /** The picture's own width divided by its height. */
  picture: number;
}

const MM_PER_CM = 10;

function toCm(value: unknown, unit: unknown): number | null {
  if (typeof value !== "number" || !(value > 0)) return null;
  if (unit === "mm") return value / MM_PER_CM;
  return unit === undefined || unit === "cm" ? value : null;
}

/**
 * @param node An image block.
 * @param widthPx The picture's width in pixels, or `null` when unknown (an SVG).
 * @param heightPx The picture's height in pixels, or `null` when unknown.
 * @returns The two ratios when both sizes are set in lengths and differ by more than `STRETCH_TOLERANCE`; otherwise `null`.
 */
export function stretchOf(node: Record<string, unknown>, widthPx: number | null, heightPx: number | null): Stretch | null {
  const width = toCm(node.width, node.width_unit);
  const height = toCm(node.height, node.height_unit);
  if (width === null || height === null || !widthPx || !heightPx) return null;
  const chosen = width / height;
  const picture = widthPx / heightPx;
  return Math.abs(chosen / picture - 1) > STRETCH_TOLERANCE ? { chosen, picture } : null;
}
