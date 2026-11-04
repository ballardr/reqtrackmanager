/**
 * Module: utils/reportPreviewMemory
 *
 * Remembers, per viewer and per layout, which projects the designer's preview was last run on.
 *
 * Responsibilities:
 * - Read and write the choice in `localStorage`, keyed by scope (organisation or project) and layout.
 * - Re-check what was stored against what the caller can still choose, so a project that was deleted or is no
 *   longer readable drops silently and the default (all projects) applies.
 *
 * Design decisions: this is a per-viewer convenience, so it never reaches the server (it is neither shared nor audited
 * state). Every storage call is wrapped: blocked or full storage means the choice lasts until the page is reloaded
 * (a module-level copy serves the reads), so the choice still holds when the panel is reopened.
 */
import type { LayoutScope } from "../api/reportLayouts";

/** What the preview remembers: the narrowed project set (organisation scope) and the child-projects switch (project scope). */
export interface RememberedPreviewScope {
  projectIds: string[];
  includeChildren: boolean;
}

const KEY_PREFIX = "reqtrack.reportPreviewScope";

/** The same choices in memory: the fallback when storage is blocked or full. */
const inMemory = new Map<string, string>();

function storageKey(scope: LayoutScope, layoutId: string): string {
  return `${KEY_PREFIX}.${scope.kind}.${scope.id}.${layoutId}`;
}

/**
 * Reads the remembered choice for a layout.
 *
 * @param scope The scope the layout is opened in.
 * @param layoutId The layout being previewed.
 * @param validProjectIds The projects the caller can currently choose; a stored id outside it is dropped.
 * @returns The remembered choice, or the defaults (no projects narrowed, children off) when nothing usable is stored.
 */
export function readPreviewScope(scope: LayoutScope, layoutId: string, validProjectIds: ReadonlySet<string>): RememberedPreviewScope {
  const empty: RememberedPreviewScope = { projectIds: [], includeChildren: false };
  try {
    const key = storageKey(scope, layoutId);
    let raw: string | null = null;
    try {
      raw = localStorage.getItem(key);
    } catch {
      // Storage can be blocked; fall back to this page's copy.
    }
    raw ??= inMemory.get(key) ?? null;
    if (raw === null) return empty;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return empty;
    const { projectIds, includeChildren } = parsed as Record<string, unknown>;
    return {
      projectIds: Array.isArray(projectIds)
        ? projectIds.filter((id): id is string => typeof id === "string" && validProjectIds.has(id))
        : [],
      includeChildren: includeChildren === true,
    };
  } catch {
    return empty;
  }
}

/**
 * Stores the choice for a layout; storage that is blocked or full is ignored.
 *
 * @param scope The scope the layout is opened in.
 * @param layoutId The layout being previewed.
 * @param choice The choice to remember.
 */
export function writePreviewScope(scope: LayoutScope, layoutId: string, choice: RememberedPreviewScope): void {
  const key = storageKey(scope, layoutId);
  const raw = JSON.stringify(choice);
  inMemory.set(key, raw);
  try {
    localStorage.setItem(key, raw);
  } catch {
    // Storage can be blocked; the in-memory copy keeps the choice until reload.
  }
}

/** Forgets every remembered choice (for tests and stories, which share one store). */
export function clearRememberedPreviewScopes(): void {
  inMemory.clear();
  try {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith(`${KEY_PREFIX}.`)) localStorage.removeItem(key);
    }
  } catch {
    // Nothing stored if storage is blocked.
  }
}
