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
 *
 * Escape only closes *this* dialog if it currently contains focus — found
 * as a real bug (not just a test-selector artifact) while adding the
 * follow-up UX batch's Phase C Playwright coverage for the "Manage users"
 * modal's per-row `MultiSelectDropdown`: every open `Modal`/`SidePanel`/
 * `Popover` registers its own independent `window` "keydown" listener, all
 * of which fire for a single Escape press regardless of nesting, since
 * `addEventListener` has no concept of "only the topmost one" on its own.
 * Without this guard, opening a `Popover` (e.g. a row's role dropdown)
 * inside a `Modal`/`SidePanel` and pressing Escape closed *both* — the
 * outer container's own contents (and whatever state it held) vanished
 * along with the popover the user actually meant to dismiss. Each
 * instance's own initial-focus effect above already moves focus inside
 * itself on open, and (since `Modal`/`SidePanel`/`Popover` are all
 * portalled to `document.body` as independent DOM subtrees, not nested
 * inside one another even when opened "inside" each other logically) only
 * the innermost currently-open one ever actually contains
 * `document.activeElement` — the same containment check the Tab-trap
 * logic just below already relies on for its own correctness.
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
