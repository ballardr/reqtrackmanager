import { useEffect, useRef, type RefObject } from "react";

export const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Shared focus-trap, focus-restoration and Escape-to-close behaviour for the floating dialog components (`Modal`,
 * `SidePanel`, `Popover`). Initial focus moves into the dialog only if nothing inside already has focus (so a child's own
 * `autoFocus`, e.g. `RichTextEditor`'s link-URL field, is kept), Tab and Shift+Tab cycle within the dialog while it is
 * open, and focus returns to whatever triggered it on close.
 *
 * Escape closes this dialog only if it currently contains focus. Every open `Modal`/`SidePanel`/`Popover` registers its
 * own `window` "keydown" listener and all fire for one Escape press, so without the guard a `Popover` opened inside a
 * `Modal` closed both. Each instance moves focus inside itself on open and all three are portalled to `document.body` as
 * independent subtrees, so only the innermost open one contains `document.activeElement` (the same containment check the
 * Tab trap relies on).
 */
export function useDialogA11y(dialogRef: RefObject<HTMLElement | null>, onClose: () => void): void {
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;
    if (dialog && !dialog.contains(document.activeElement)) {
      const first = dialog.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
      (first ?? dialog).focus();
    }
    return () => {
      previouslyFocused.current?.focus();
    };
  }, [dialogRef]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        const dialog = dialogRef.current;
        if (!dialog || !dialog.contains(document.activeElement)) return;
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const dialog = dialogRef.current;
      if (!dialog) return;
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [dialogRef, onClose]);
}
