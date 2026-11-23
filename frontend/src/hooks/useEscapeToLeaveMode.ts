/**
 * Module: hooks/useEscapeToLeaveMode
 *
 * Lets Escape turn off a canvas mode (note mode, comment mode) that stays on until it is switched off.
 *
 * Design decisions: one document listener in the bubble phase, so a dialog, pop-over or field that handles Escape
 * first (and marks it handled) keeps it; it never acts while text is being typed or a dialog, menu or pop-over is
 * open (the `historyShortcutBlocked` rule).
 */
import { useEffect } from "react";

import { historyShortcutBlocked } from "./useHistoryShortcuts";
import { useLatest } from "./useLatest";

/**
 * @param active Whether the mode is on; the listener is registered only then.
 * @param leave Called when Escape is pressed with the mode on and nothing else owning the key.
 */
export function useEscapeToLeaveMode(active: boolean, leave: () => void): void {
  const latest = useLatest(leave);
  useEffect(() => {
    if (!active) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape" || event.defaultPrevented || event.isComposing || historyShortcutBlocked(event.target)) return;
      latest.current();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [active, latest]);
}
