/**
 * Module: utils/canvasFocus
 *
 * Returns keyboard focus from a text field in an editor's Selection card to the
 * selected item on the graph canvas: on Escape, it focuses the selected node or
 * line (React Flow draws each with its id in `data-id`), so Delete or the arrow
 * keys work without the pointer.
 * Design: Escape already means "leave this field"; a field inside a dialog or an
 * open menu keeps it for closing that (`overlayIsOpen`), as does any handler that
 * already acted on it. Leaving the field is what stores a name in the editors,
 * so when a value is saved is unchanged.
 */
import type { KeyboardEvent } from "react";

import { overlayIsOpen } from "./keyboardTargets";

/** The selected item of a canvas: a node or a line (a leader included) by its id. */
interface CanvasSelection { kind: string; id: string }

/**
 * Focuses the canvas element of `selection`.
 *
 * @param selection The selected item, or null for none.
 * @param root The document to look in.
 * @returns True when an element was found and focused.
 */
export function focusCanvasSelection(selection: CanvasSelection | null, root: Document = document): boolean {
  if (!selection) return false;
  const id = CSS.escape(selection.id);
  const element = root.querySelector<HTMLElement>(`.react-flow__node[data-id="${id}"], .react-flow__edge[data-id="${id}"]`);
  if (!element) return false;
  element.focus();
  return true;
}

/**
 * A key handler for a Selection card: Escape in a text input or text area moves the focus to the selected item on the canvas.
 *
 * @param event The key press, from the card.
 * @param selection The canvas selection the card is showing.
 */
export function returnFocusToCanvas(event: KeyboardEvent<HTMLElement>, selection: CanvasSelection | null): void {
  if (event.key !== "Escape" || event.defaultPrevented || !selection) return;
  const target = event.target;
  if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) || overlayIsOpen()) return;
  if (focusCanvasSelection(selection)) event.preventDefault();
}
