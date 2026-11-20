/**
 * Module: hooks/useMarkdownEditorView
 *
 * The person's last chosen view of a Markdown field (Visual or Write), shared by every Markdown field.
 *
 * Design decisions:
 * - A per-viewer convenience: kept in `localStorage`, never sent to the server. Every storage call is wrapped;
 *   blocked storage means the choice lasts until the page is reloaded (a module-level copy serves reads).
 * - Visual until the person chooses Write. Only an explicit choice is stored: a field that falls back to Write
 *   because its text cannot be edited visually does not change the preference.
 * - Preview is a way to check the result, not an editing style, so it is never stored.
 */
import { useCallback, useSyncExternalStore } from "react";

export type MarkdownEditingView = "visual" | "write";

const STORAGE_KEY = "reqtrack.markdownEditorView";
let remembered: MarkdownEditingView = "visual";
/** True once a write was refused, so a missing stored value no longer means the default. */
let writeFailed = false;
const listeners = new Set<() => void>();

function read(): MarkdownEditingView {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "visual" || raw === "write") remembered = raw;
    else if (!writeFailed) remembered = "visual";
  } catch {
    // Storage can be blocked; the page's copy is used.
  }
  return remembered;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

/** @returns The remembered editing view and a function that stores a new choice. */
export function useMarkdownEditorView(): [MarkdownEditingView, (view: MarkdownEditingView) => void] {
  const view = useSyncExternalStore(subscribe, read, () => "visual" as const);
  const choose = useCallback((next: MarkdownEditingView) => {
    remembered = next;
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Blocked storage: the choice lasts for this page.
      writeFailed = true;
    }
    listeners.forEach((listener) => listener());
  }, []);
  return [view, choose];
}
