/**
 * Module: modules/architecture/useSymbolLibrary
 *
 * Reads the symbol library page of a project or the organisation: the rows after the server's filters and sort, paged
 * ("Show more" appends the next page), with the figures the page needs besides the rows. The server does the filtering and
 * sorting, so a long library is never loaded whole and a sort covers every row, not only the loaded ones.
 *
 * Design decisions:
 * - A change of filter, sort or place starts a fresh read; a slower earlier answer is dropped (`useRequestSequence`).
 * - The first read after a return to the page asks for as many rows as were loaded when the person left (`useRestoredRowCount`),
 *   so the list position can be restored.
 */
import { useState } from "react";

import { toErrorMessage } from "../../context/ToastContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useRestoredRowCount } from "../../hooks/useListPosition";
import { useRequestSequence } from "../../hooks/useRequestSequence";
import { symbolApi, type SymbolLibraryFilters } from "./api";
import type { TypesScope } from "./ArchitectureTypesPanel";
import type { SymbolLibraryPage, SymbolLibraryRow } from "./types";

/** Rows in a page of the library. */
export const SYMBOL_PAGE_SIZE = 60;

/** What `useSymbolLibrary` returns. */
export interface SymbolLibrary {
  /** The rows loaded so far, or `null` until the first page arrives. */
  rows: SymbolLibraryRow[] | null;
  /** Rows matching the filters (loaded or not). */
  total: number;
  /** Rows in the library before any filter. */
  libraryTotal: number;
  converterAvailable: boolean;
  error: string | null;
  /** Appends the next page. */
  loadMore: () => void;
}

/**
 * @param scope The project or organisation whose library is read.
 * @param filters The filters and sort, by the names the endpoint takes (no paging).
 * @param refreshKey A counter the page bumps after a change, which reads the first page again.
 * @param onPage Called with each page as it arrives (a project's page takes the organisation's folders from it).
 * @returns The rows, the totals and the call to load more.
 */
export function useSymbolLibrary(
  scope: TypesScope, filters: SymbolLibraryFilters, refreshKey: number, onPage?: (page: SymbolLibraryPage) => void,
): SymbolLibrary {
  const [page, setPage] = useState<SymbolLibraryPage | null>(null);
  const [rows, setRows] = useState<SymbolLibraryRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const begin = useRequestSequence();
  const limitFor = useRestoredRowCount(SYMBOL_PAGE_SIZE);
  const scopeId = scope.kind === "project" ? scope.projectId : scope.organizationId;

  async function read(offset: number, append: boolean) {
    const isLatest = begin();
    try {
      const request = { ...filters, offset, limit: limitFor(offset) };
      const answer = await (scope.kind === "project" ? symbolApi.projectLibrary(scopeId, request) : symbolApi.orgLibrary(scopeId, request));
      if (!isLatest()) return;
      setPage(answer);
      setRows((current) => (append && current ? [...current, ...answer.items] : answer.items));
      setError(null);
      onPage?.(answer);
    } catch (err) {
      if (isLatest()) setError(toErrorMessage(err, "Could not load the symbol library."));
    }
  }

  // A change of filter, sort, place or the refresh counter reads the first page again.
  useLoadOnChange(() => read(0, false), [scope.kind, scopeId, filters, refreshKey]);

  return {
    rows,
    total: page?.total ?? 0,
    libraryTotal: page?.library_total ?? 0,
    converterAvailable: page?.converter_available ?? false,
    error,
    loadMore: () => { if (rows) void read(rows.length, true); },
  };
}
