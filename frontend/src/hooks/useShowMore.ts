/**
 * Module: hooks/useShowMore
 *
 * Client-side paging for a list that is loaded whole (report layouts, packs, placements): the first page of rows and
 * the next page on request, returning to the first page whenever the filter changes.
 */
import { useCallback, useState } from "react";

export const REPORT_LIST_PAGE_SIZE = 25;

/**
 * @param total How many rows there are in all (after filtering).
 * @param resetKey Changing it returns to the first page (pass the filter's text).
 * @returns How many rows to show and a function to show the next page.
 */
export function useShowMore(total: number, resetKey: string): { limit: number; more: () => void } {
  const [state, setState] = useState({ key: resetKey, pages: 1 });
  const pages = state.key === resetKey ? state.pages : 1;
  const more = useCallback(() => setState({ key: resetKey, pages: pages + 1 }), [resetKey, pages]);
  return { limit: Math.min(total, pages * REPORT_LIST_PAGE_SIZE), more };
}

