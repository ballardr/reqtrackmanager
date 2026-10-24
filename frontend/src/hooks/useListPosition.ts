/**
 * Module: hooks/useListPosition
 *
 * Keeps a list page's place: after opening a record and coming back, the list shows the same rows
 * at the same scroll offset (docs/ux-style-guide.md, "Pattern: list position").
 *
 * Responsibilities:
 * - `useListPosition` (used once, by `ListPageLayout`): saves the window scroll offset and the number
 *   of rows loaded when the list unmounts, restores the offset once its rows have rendered, and starts a
 *   fresh visit at the top.
 * - `useRestoredRowCount` (used by a paginated page): the number of rows the first load should ask for so
 *   the rows the person had loaded ("Show more") exist again before the offset is restored.
 * - `listBackTarget` (used by `RecordHeader`): the record's own "back to list" link, which lands on the
 *   list as it was left (same filters) and restores its position, like the browser's Back button.
 *
 * Design decisions:
 * - The position is keyed by path plus query string, so the URL must carry the list's filters: a saved
 *   position is never applied to a list with different filters.
 * - Restored on back navigation (POP) or when a navigation carries `RESTORE_STATE`; a fresh visit (a nav
 *   link, a typed address, a new tab) starts at the top. A position saved by an earlier page load is only
 *   used when the browser itself is restoring (a reload, or Back across page loads), since React Router
 *   reports every page load as POP.
 * - `sessionStorage` (per tab, gone when the tab closes). Every access is guarded: with storage blocked
 *   the list simply starts at the top.
 * - The window is the scroll container (the app shell does not scroll an inner element).
 */
import { useLayoutEffect, useRef, useState } from "react";
import { useLocation, useNavigationType, type Location } from "react-router-dom";

/** Navigation state a link sets to ask the list it opens to restore its saved position. */
export const RESTORE_STATE = { restoreListPosition: true } as const;

interface SavedPosition {
  scrollY: number;
  loaded: number;
  /** The page load that saved it (`DOCUMENT`). */
  document: string;
}

/** Identifies this page load, so a position saved by an earlier one can be told apart. */
const DOCUMENT = Math.random().toString(36).slice(2);

const POSITION_PREFIX = "list-position:";
const LAST_SEARCH_PREFIX = "list-last-search:";

/** Keys whose saved row count has already been used by a first load in this tab session, so it is used once. */
const consumed = new Set<string>();

function locationKey(pathname: string, search: string): string {
  return `${pathname}${search}`;
}

function readPosition(key: string): SavedPosition | null {
  try {
    const raw = sessionStorage.getItem(POSITION_PREFIX + key);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return null;
    const { scrollY, loaded, document } = parsed as Partial<SavedPosition>;
    if (typeof scrollY !== "number" || typeof loaded !== "number" || typeof document !== "string") return null;
    return { scrollY, loaded, document };
  } catch {
    return null;
  }
}

function writePosition(pathname: string, search: string, position: Omit<SavedPosition, "document">): void {
  try {
    sessionStorage.setItem(POSITION_PREFIX + locationKey(pathname, search), JSON.stringify({ ...position, document: DOCUMENT }));
    sessionStorage.setItem(LAST_SEARCH_PREFIX + pathname, search);
  } catch {
    // Storage blocked or full: the list just starts at the top next time.
  }
}

/** How this navigation asks for the saved position: browser Back/Forward (`pop`) or a link that says so (`link`). */
interface RestoreIntent {
  pop: boolean;
  link: boolean;
}

function restoreIntent(navigationType: string, location: Pick<Location, "state">): RestoreIntent {
  const state = location.state as { restoreListPosition?: boolean } | null;
  return { pop: navigationType === "POP", link: state?.restoreListPosition === true };
}

/** Whether the browser itself is restoring the page (a reload, or Back across page loads) rather than opening it fresh. */
function browserIsRestoring(): boolean {
  const entry = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
  return entry !== undefined && entry.type !== "navigate";
}

/** The saved position this navigation may use, or null for a fresh visit. */
function restorablePosition(key: string, intent: RestoreIntent): SavedPosition | null {
  if (!intent.pop && !intent.link) return null;
  const saved = readPosition(key);
  if (!saved) return null;
  return intent.link || saved.document === DOCUMENT || browserIsRestoring() ? saved : null;
}

/**
 * Saves, restores and resets the list's scroll position.
 *
 * @param ready True once the list's rows are rendered (not while a load is in flight); nothing is saved or
 *   restored before then, because an empty list has no height to scroll.
 * @param loaded The number of rows currently loaded, remembered so a paginated list can reload them.
 */
export function useListPosition({ ready, loaded = 0 }: { ready: boolean; loaded?: number }): void {
  const location = useLocation();
  const navigationType = useNavigationType();
  const where = useRef({ pathname: location.pathname, search: location.search });
  const latest = useRef({ ready, loaded });
  const intent = useRef(restoreIntent(navigationType, location));
  const settled = useRef(false);

  useLayoutEffect(() => {
    where.current = { pathname: location.pathname, search: location.search };
    latest.current = { ready, loaded };
  });

  // Remember the filters the list is showing as they change, not only when it unmounts: the record that is
  // opening renders its "back to list" link before this list's cleanup has run.
  useLayoutEffect(() => {
    try {
      sessionStorage.setItem(LAST_SEARCH_PREFIX + location.pathname, location.search);
    } catch {
      // Storage blocked: the back link goes to the plain list.
    }
  }, [location.pathname, location.search]);

  // Save on unmount, while the page's height (and so the offset) is still intact.
  useLayoutEffect(() => () => {
    if (!latest.current.ready) return;
    writePosition(where.current.pathname, where.current.search, { scrollY: window.scrollY, loaded: latest.current.loaded });
  }, []);

  // Once the rows exist, put the page back where it was, or at the top for a fresh visit.
  useLayoutEffect(() => {
    if (!ready || settled.current) return;
    settled.current = true;
    const key = locationKey(location.pathname, location.search);
    const saved = restorablePosition(key, intent.current);
    if (!saved) {
      window.scrollTo(0, 0);
      return;
    }
    consumed.add(key);
    let frames = 0;
    const apply = () => {
      window.scrollTo(0, saved.scrollY);
      const reachable = document.documentElement.scrollHeight - window.innerHeight;
      // Late layout (images, the filter panel) can leave the page too short for a moment: retry briefly.
      if (reachable < saved.scrollY && frames++ < 10) requestAnimationFrame(apply);
    };
    apply();
  }, [ready, location.pathname, location.search]);
}

/**
 * The page-size a paginated list's first load should use so previously loaded rows come back.
 *
 * @param pageSize The normal page size.
 * @returns `limitFor(offset)`: `pageSize`, except on an offset-0 load that follows back navigation to a list
 *   which had more rows loaded, where it is that larger count (once per return).
 */
export function useRestoredRowCount(pageSize: number): (offset: number) => number {
  const location = useLocation();
  const navigationType = useNavigationType();
  const intent = useRef(restoreIntent(navigationType, location));
  useState(() => {
    // A new mount is a new return: forget that an earlier visit used the saved count.
    consumed.delete(locationKey(location.pathname, location.search));
  });
  const latestLocation = useRef(location);
  useLayoutEffect(() => {
    latestLocation.current = location;
  });
  return (offset: number) => {
    if (offset !== 0) return pageSize;
    const key = locationKey(latestLocation.current.pathname, latestLocation.current.search);
    if (consumed.has(key)) return pageSize;
    const saved = restorablePosition(key, intent.current);
    return saved && saved.loaded > pageSize ? saved.loaded : pageSize;
  };
}

/**
 * Where a record's "back to list" link should go so the list comes back as it was left.
 *
 * @param listPath The list's path, optionally with a query that selects it (`/people?kind=persona`).
 * @returns `to` (the path plus the filters the list was last left with, when those still satisfy the link's
 *   own query) and `state` asking the list to restore its position.
 */
export function listBackTarget(listPath: string): { to: string; state: typeof RESTORE_STATE } {
  const [path, ownQuery = ""] = listPath.split("?");
  let search = ownQuery ? `?${ownQuery}` : "";
  try {
    const saved = sessionStorage.getItem(LAST_SEARCH_PREFIX + path);
    if (saved !== null) {
      const savedParams = new URLSearchParams(saved);
      const named = [...new URLSearchParams(ownQuery)];
      if (named.every(([key, value]) => savedParams.get(key) === value)) search = saved;
    }
  } catch {
    // Storage blocked: link to the list as given.
  }
  return { to: `${path}${search}`, state: RESTORE_STATE };
}
