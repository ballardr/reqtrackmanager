/**
 * Module: hooks/useListSort
 *
 * The sort of a record list: the one state behind the filter panel's **Sort by** and **Order** fields and the table's
 * column headers, so the two can never disagree (docs/ux-style-guide.md, "Pattern: list sort").
 *
 * Responsibilities:
 * - Read the sort from the address (`sort`, `order`), else the person's last choice for this list (kept in
 *   `ui_preferences` as `list_sort_<key>`, so it follows them between browsers), else the list's default, which is the
 *   code ascending. The effective sort is never empty, so the table always shows what orders it.
 * - Write a chosen sort to the address and the preference; reset removes both.
 * - Offer the header click (`onHeaderSort`): another column ascending, the same column descending, then the default.
 *
 * Design decisions:
 * - The address wins over the stored choice, so a shared link opens in the order its sender saw.
 * - A stored key the list no longer offers is ignored (a column removed in a later release) rather than trusted.
 * - The preference is read from the auth context directly, so a list rendered on its own (a story) still sorts.
 * - A list that holds its whole set in the browser orders with `sortRows`; a paged list sends `sort` and `order` to
 *   the server (`sortParams`). Either way the keys are the same four common ones (`code`, `title`, `created`,
 *   `modified`) plus the list's own columns.
 *
 * Dependencies: `useUrlSort` (the address), `AuthContext` (the stored choice).
 */
import { useCallback, useContext, useMemo, useState } from "react";

import { cycleSort, type SortState } from "../components/sortState";
import { AuthContext } from "../context/AuthContextValue";
import { useUrlSort } from "./useUrlFilter";

/** The keys every record list offers after its own columns: when the record was created and last changed. */
export const TIME_SORT_KEYS = ["created", "modified"] as const;

/** The state of one list's sort, from `useListSort`. */
export interface ListSortState {
  /** The sort in force: the address, else the remembered choice, else the default. Never empty. */
  sort: SortState;
  /** The keys the list offers. */
  keys: readonly string[];
  /** Whether the sort in force is the list's default (nothing chosen, so there is nothing to reset). */
  isDefault: boolean;
  /** Chooses a sort: written to the address and remembered for this list. */
  set: (next: SortState) => void;
  /** A column header was clicked: that column ascending, descending if it already was, then the default. */
  onHeaderSort: (key: string) => void;
  /** Removes the chosen sort from the address and the preference, so the default applies again. */
  reset: () => void;
}

function storedSort(value: unknown, keys: readonly string[]): SortState | null {
  if (typeof value !== "string") return null;
  const [key, order] = value.split(":");
  if (!keys.includes(key)) return null;
  return { key, direction: order === "desc" ? "desc" : "asc" };
}

/**
 * @param listKey Names the list for the remembered choice, e.g. `decisions` (one per list page, never shared).
 * @param keys Every sort key the list offers: its sortable column keys and `TIME_SORT_KEYS`.
 * @param defaultKey The key of the default order, ascending: the list's code column key.
 * @param local Keep the chosen sort in the component instead of the address, for a list embedded in another page (an
 *   organisation panel) whose own parameters must stay alone; the remembered choice still applies.
 * @returns The state to pass to `SortField` and, as `sort` and `onHeaderSort`, to the table.
 */
export function useListSort(listKey: string, keys: readonly string[], defaultKey: string, local = false): ListSortState {
  const [urlSort, setUrl] = useUrlSort<string>(keys);
  const [localSort, setLocal] = useState<SortState | null>(null);
  const fromUrl = local ? localSort : urlSort;
  const auth = useContext(AuthContext);
  const prefKey = `list_sort_${listKey}`;
  const stored = storedSort(auth?.user?.ui_preferences[prefKey], keys);
  const setPreference = auth?.setUiPreference;
  const chosen = fromUrl ?? stored;
  const sort = useMemo<SortState>(() => chosen ?? { key: defaultKey, direction: "asc" }, [chosen, defaultKey]);

  const set = useCallback(
    (next: SortState) => {
      if (local) setLocal(next);
      else setUrl(next);
      setPreference?.(prefKey, `${next.key}:${next.direction}`);
    },
    [local, setUrl, setPreference, prefKey],
  );
  const reset = useCallback(() => {
    if (local) setLocal(null);
    else setUrl(null);
    setPreference?.(prefKey, null);
  }, [local, setUrl, setPreference, prefKey]);
  const onHeaderSort = useCallback(
    (key: string) => {
      const next = cycleSort<string>(sort, key);
      if (next === null) reset();
      else set(next);
    },
    [sort, set, reset],
  );

  return { sort, keys, isDefault: chosen === null, set, onHeaderSort, reset };
}

/**
 * The sort as the query parameters a request or a list's Export takes.
 *
 * @param params The parameters so far (changed and returned).
 * @param sort The sort in force.
 */
export function addSortParams(params: URLSearchParams, sort: SortState): URLSearchParams {
  params.set("sort", sort.key);
  params.set("order", sort.direction);
  return params;
}
