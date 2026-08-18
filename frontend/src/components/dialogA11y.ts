import { useEffect, useRef, type RefObject } from "react";

export const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Shared focus-trap + focus-restoration + Escape-to-close behaviour for
 * this app's floating dialog components (`Modal`, `SidePanel`, `Popover`).
 * Extracted once all three needed the identical logic, rather than
 * duplicated per component: moves initial focus into the dialog only if
 * nothing inside it already has focus (so a child's own `autoFocus`, e.g.
 * `RichTextEditor`'s link-URL field, isn't stolen back), cycles Tab/Shift+Tab
 * within the dialog while it's open, and restores focus to whatever
 * triggered it once it closes.
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
