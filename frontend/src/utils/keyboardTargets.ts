/**
 * Module: utils/keyboardTargets
 *
 * Where a key press belongs to something other than an editor's own shortcut
 * (Undo, Redo, Delete): whether it happened in a text-entry control (which keeps
 * its keys for its text) and whether a dialog, menu or pop-over is open over the
 * page (which owns the keyboard). Plain functions over the DOM, shared by every
 * editor shortcut and testable without a browser event.
 */

/** Elements that open over the page and own the keyboard while they are shown. */
const OVERLAY_SELECTOR = '[role="dialog"], [role="alertdialog"], [role="menu"], [aria-modal="true"]';

/**
 * @param target Where the key press happened.
 * @returns True for an input, a text area, a select or editable text, or anything inside one.
 */
export function isTextEntryTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || target.closest("input, textarea, select") !== null;
}

/**
 * @param root The document to look in.
 * @returns True when a dialog, menu or pop-over is open.
 */
export function overlayIsOpen(root: Document = document): boolean {
  return root.querySelector(OVERLAY_SELECTOR) !== null;
}
