/**
 * Module: navigation/projectNav
 *
 * Pure logic for the per-user "Project" nav-rail section layout
 * (docs/plans/platform-enhancements-2026-10-plan.md Phase 4): which items show in which
 * order, and which sit behind "More".
 *
 * Responsibilities:
 * - Define the stored preference shape (`NavPref`) and its `ui_preferences` keys: the user's
 *   default (`project_nav`) and an optional per-project override (`project_nav:<projectId>`).
 * - Validate whatever was stored (the bag is open-ended JSON) rather than trust it.
 * - Arrange the *currently available* items against a stored preference, tolerating keys that
 *   no longer exist (module disabled) and items the preference predates (module enabled).
 * - Lift the item for the current route out of "More" so a user is never stranded on a page
 *   whose link is hidden.
 *
 * Design decisions:
 * - "Hide" means "move behind More", never remove. `PINNED_NAV_KEYS` cannot go into More
 *   (Overview, and Admin — a hidden Admin link strands whoever needs it).
 * - The preference stores the full order (main items then More items) plus the More subset,
 *   so More's own order is user-controlled too.
 * - An item missing from the stored order (a newly enabled module) is inserted after its
 *   nearest preceding default-order neighbour, so it appears where it would by default
 *   instead of vanishing or jumping to an end.
 * - Items are generic (`key`, `to`, `exact`); module items are keyed `<module_key>:<nav_path>`
 *   by the caller, so this file never names a module.
 */

import type { ReactNode } from "react";

/** Items that can be reordered but never moved into "More". */
export const PINNED_NAV_KEYS: readonly string[] = ["overview", "admin"];

/** `ui_preferences` key holding the user's default layout for every project. */
export const PROJECT_NAV_PREF_KEY = "project_nav";

/** Prefix of the per-project override keys (`project_nav:<projectId>`). */
export const PROJECT_NAV_OVERRIDE_PREFIX = "project_nav:";

/** Stored layout: `order` lists every item (main items first, then More items); `more` is the subset behind More. */
export type NavPref = {
  order: string[];
  more: string[];
};

/** The minimum an item needs for layout and active-route detection. */
export interface NavItemLike {
  key: string;
  to: string;
  exact?: boolean;
}

/** One entry of the Project nav section. Module entries use the key `<module_key>:<nav_path>`. */
export interface ProjectNavItem extends NavItemLike {
  label: string;
  icon: ReactNode;
}

/** The `ui_preferences` key of one project's override. */
export function projectNavOverrideKey(projectId: string): string {
  return `${PROJECT_NAV_OVERRIDE_PREFIX}${projectId}`;
}

/**
 * Whether a nav link is the active one for `pathname` — the single definition `NavRailLink`
 * and the "More" lifting both use, so they cannot disagree.
 *
 * Args:
 *   pathname: The current location's path.
 *   to: The link's target path.
 *   exact: Match only the exact path rather than any path beneath it.
 */
export function isNavPathActive(pathname: string, to: string, exact = false): boolean {
  return exact ? pathname === to : pathname.startsWith(to);
}

function isStringList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((entry) => typeof entry === "string");
}

/** Validates a stored value as a `NavPref`; returns `null` for anything malformed. */
export function parseNavPref(raw: unknown): NavPref | null {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const { order, more } = raw as Record<string, unknown>;
  if (!isStringList(order) || !isStringList(more)) return null;
  return { order, more };
}

/**
 * Picks the stored layout in effect for a project: its override, else the user's default.
 * A malformed override falls through to the default rather than hiding the whole section.
 * `null` means "use the product default".
 */
export function resolveNavPref(userDefault: unknown, override: unknown): NavPref | null {
  return parseNavPref(override) ?? parseNavPref(userDefault);
}

/** Items split into the always-visible list and the "More" list, each in display order. */
export interface NavArrangement<T extends NavItemLike> {
  main: T[];
  more: T[];
}

/**
 * Arranges `items` (given in product-default order) per `pref`, without any route awareness
 * (the editor edits this form).
 *
 * Args:
 *   items: Every currently available item, in product-default order.
 *   pref: The stored layout, or `null` for the product default.
 *
 * Returns:
 *   `main` and `more` in display order. Unknown stored keys are dropped; items the preference
 *   does not mention are inserted at their default position and stay in `main`.
 */
export function arrangeProjectNav<T extends NavItemLike>(items: T[], pref: NavPref | null): NavArrangement<T> {
  if (!pref) return { main: [...items], more: [] };

  const byKey = new Map(items.map((item) => [item.key, item]));
  const ordered: string[] = [];
  for (const key of pref.order) {
    if (byKey.has(key) && !ordered.includes(key)) ordered.push(key);
  }
  items.forEach((item, index) => {
    if (ordered.includes(item.key)) return;
    let insertAt = 0;
    for (let prev = index - 1; prev >= 0; prev -= 1) {
      const neighbourAt = ordered.indexOf(items[prev].key);
      if (neighbourAt !== -1) {
        insertAt = neighbourAt + 1;
        break;
      }
    }
    ordered.splice(insertAt, 0, item.key);
  });

  const moreKeys = new Set(pref.more.filter((key) => !PINNED_NAV_KEYS.includes(key)));
  const main: T[] = [];
  const more: T[] = [];
  for (const key of ordered) {
    const item = byKey.get(key)!;
    (moreKeys.has(key) ? more : main).push(item);
  }
  return { main, more };
}

/**
 * `arrangeProjectNav` plus the active-route guarantee: any More item whose link is active for
 * `pathname` is shown at the end of the main list instead, so the current page is never hidden.
 */
export function layoutProjectNav<T extends NavItemLike>(items: T[], pref: NavPref | null, pathname: string): NavArrangement<T> {
  const { main, more } = arrangeProjectNav(items, pref);
  const lifted = more.filter((item) => isNavPathActive(pathname, item.to, item.exact));
  if (lifted.length === 0) return { main, more };
  return { main: [...main, ...lifted], more: more.filter((item) => !lifted.includes(item)) };
}

/** Builds the `NavPref` to store from an editor's final arrangement. */
export function navPrefFromArrangement(main: NavItemLike[], more: NavItemLike[]): NavPref {
  return { order: [...main, ...more].map((item) => item.key), more: more.map((item) => item.key) };
}
