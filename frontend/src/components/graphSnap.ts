/**
 * Module: components/graphSnap
 *
 * The grid rule of the shared graph canvas: pure functions, no React, so the canvas and its tests share one rule.
 *
 * Responsibilities: snap one coordinate, and the edges a resize moved, to a grid; say whether snapping applies to a move
 * (the person's setting, inverted while the invert key is held during a drag or resize); read whether the invert key is
 * held from an event's own modifier flags, so a key-up the page never received (swallowed by a screenshot shortcut)
 * cannot leave it counted as held.
 *
 * Design decisions: the grid is in absolute canvas coordinates, so a nested box snaps to the same grid as a top-level
 * one. A resize snaps by edges: each moved edge lands on a grid line, so the size changes to fit rather than being
 * rounded alone (which would leave an off-grid right edge); an unmoved edge stays. Halves round up (`Math.round`), so a
 * coordinate exactly between two lines, negative ones included, snaps the same way on every run.
 */

/** A box in canvas units: top-left corner and size. */
export interface SnapBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * Snaps one coordinate to the nearest grid line.
 *
 * @param value A coordinate in canvas units (negative allowed).
 * @param size The grid size in canvas units; a size of 0 or less leaves the value as it is.
 * @returns The nearest multiple of `size`.
 */
export function snapCoordinate(value: number, size: number): number {
  if (!(size > 0)) return value;
  // `+ 0` turns a negative zero into 0, so a coordinate just below a line does not read as -0.
  return Math.round(value / size) * size + 0;
}

/**
 * Snaps the edges a resize moved to the grid and leaves the others where they were, so a resize from the bottom right corner
 * never moves a box whose top left corner is off the grid. The size never drops below `minWidth`/`minHeight` (rounded up to a
 * whole number of grid steps), so a small box is not collapsed by snapping.
 *
 * @param before The box as it was when the resize began.
 * @param after The box the resize reached.
 * @param size The grid size in canvas units.
 * @param minWidth The smallest width allowed (default: one grid step).
 * @param minHeight The smallest height allowed (default: one grid step).
 * @returns `after` with each edge that differs from `before` put on the grid.
 */
export function snapResize(before: SnapBox, after: SnapBox, size: number, minWidth = size, minHeight = size): SnapBox {
  if (!(size > 0)) return after;
  const left = after.x !== before.x ? snapCoordinate(after.x, size) : after.x;
  const top = after.y !== before.y ? snapCoordinate(after.y, size) : after.y;
  const rightMoved = after.x + after.width !== before.x + before.width;
  const bottomMoved = after.y + after.height !== before.y + before.height;
  const right = rightMoved ? snapCoordinate(after.x + after.width, size) : after.x + after.width;
  const bottom = bottomMoved ? snapCoordinate(after.y + after.height, size) : after.y + after.height;
  const minW = Math.ceil(minWidth / size) * size;
  const minH = Math.ceil(minHeight / size) * size;
  // A box held at its minimum keeps the edge that did not move, so the minimum is taken from the fixed side.
  const width = Math.max(right - left, minW);
  const height = Math.max(bottom - top, minH);
  const x = after.x !== before.x && right - left < minW ? right - width : left;
  const y = after.y !== before.y && bottom - top < minH ? bottom - height : top;
  return { x, y, width, height };
}

/**
 * Whether a move or resize snaps.
 *
 * @param setting The person's Snap to grid setting.
 * @param invertHeld True while the invert key is held.
 * @param gesture True while a box is being dragged or resized by pointer; the key inverts only then, so it never changes how a
 *   key-driven move behaves.
 * @returns True when the move snaps: the setting, inverted by the key during a pointer gesture.
 */
export function snapApplies(setting: boolean, invertHeld: boolean, gesture: boolean): boolean {
  return setting !== (invertHeld && gesture);
}

/** The modifier flags every keyboard and pointer event carries. */
export interface ModifierFlags {
  shiftKey: boolean;
  altKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
}

/**
 * Whether the invert key is held, read from an event's modifier flags.
 *
 * @param event Any keyboard or pointer event (or an object with its modifier flags).
 * @param key The invert key's `KeyboardEvent.key` value (`Shift`, `Alt`, `Control` or `Meta`).
 * @returns True or false for a modifier key, whatever earlier events said; undefined for any other key, which has no flag
 *   and is tracked from its key-down and key-up events instead.
 */
export function invertKeyHeld(event: ModifierFlags, key: string): boolean | undefined {
  switch (key) {
    case "Shift": return event.shiftKey;
    case "Alt": return event.altKey;
    case "Control": return event.ctrlKey;
    case "Meta": return event.metaKey;
    default: return undefined;
  }
}
