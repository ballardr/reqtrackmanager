/**
 * Module: hooks/useSnapToGrid
 *
 * The person's Snap to grid preference for the shared graph canvas, and the canvas props that apply it.
 *
 * Responsibilities:
 * - Keep one on/off choice for every canvas editor in this browser, so switching it on in one editor holds in the others
 *   and in every open tab.
 * - Give the props a `GraphCanvas` takes (grid size, setting, invert key).
 *
 * Design decisions:
 * - A per-viewer convenience: kept in `localStorage`, never sent to the server, and not part of any diagram, so it
 *   changes nothing another person sees and needs no bundle entry. Every storage call is wrapped; blocked storage means the
 *   choice lasts until the page is reloaded (a module-level copy serves reads) and the canvas still renders.
 * - Off by default. Switching it on moves no existing box.
 */
import { useCallback, useSyncExternalStore } from "react";

/** The grid size in canvas units. */
export const SNAP_GRID_SIZE = 20;
/** The key that inverts the setting for one drag or resize. */
export const SNAP_INVERT_KEY = "Shift";

const STORAGE_KEY = "reqtrack.canvasSnapToGrid";

/** The choice in memory: the fallback when storage cannot be read or written. */
let remembered = false;
/** True once a write was refused, so a missing stored value no longer means "off". */
let writeFailed = false;
const listeners = new Set<() => void>();

/** Reads the stored choice, falling back to this page's copy. */
function read(): boolean {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw !== null) remembered = raw === "1";
    else if (!writeFailed) remembered = false;
  } catch {
    // Storage can be blocked; the page's copy is used.
  }
  return remembered;
}

/** Tells every subscriber the choice may have changed. */
function notify() {
  for (const listener of listeners) listener();
}

/**
 * @param listener Called when the choice changes in this page or, through the storage event, in another tab.
 * @returns A function that removes the listener.
 */
function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => { if (event.key === STORAGE_KEY || event.key === null) listener(); };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

/** The props `GraphCanvas` takes to apply the preference. */
export interface SnapCanvasProps {
  snapGrid: number;
  snapOn: boolean;
  snapInvertKey: string;
}

/**
 * @returns `on` (the stored choice), `setOn` (stores and applies a new one) and `canvasProps` (spread onto `GraphCanvas`).
 */
export function useSnapToGrid(): { on: boolean; setOn: (next: boolean) => void; canvasProps: SnapCanvasProps } {
  const on = useSyncExternalStore(subscribe, read, () => false);
  const setOn = useCallback((next: boolean) => {
    remembered = next;
    try {
      localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
    } catch {
      // Storage can be blocked or full; the choice then lasts until the page is reloaded.
      writeFailed = true;
    }
    notify();
  }, []);
  return { on, setOn, canvasProps: { snapGrid: SNAP_GRID_SIZE, snapOn: on, snapInvertKey: SNAP_INVERT_KEY } };
}
