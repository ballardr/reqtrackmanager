/**
 * Module: modules/architecture/SymbolLibraryTable
 *
 * The table view of the symbol library page: a `DirectoryTable` with a checkbox column (the rows that can be filed), the
 * drawing, the name with its badges, the source, the folder, where the symbol is used and the row's actions. Name, Source and
 * Folder sort on a header click, and the sort is the server's (the page passes `sort` and `onSort`), so it covers every row.
 * Text a person typed (a name, a folder path) is drawn with `CellText`, so a long one never changes the table's shape.
 */
import type { ReactNode } from "react";

import { ActionMenu } from "../../components/ActionMenu";
import { CellText } from "../../components/CellText";
import { DirectoryTable, type DirectoryColumn, type DirectoryTableSelection } from "../../components/DirectoryTable";
import type { SortState } from "../../components/sortState";
import { SymbolImage } from "./SymbolImage";
import { sourceText, symbolRowActions, type SymbolRowActionContext } from "./symbolLibraryActions";
import { SymbolBadges, UsedBy } from "./symbolLibraryRows";
import type { SymbolLibraryRow } from "./types";

/**
 * @param rows The loaded rows.
 * @param urlFor The API path of a symbol's content.
 * @param organizationLabel What the organisation is called (its badge in a project).
 * @param actions What the rows' menus offer, or `null` where the person may not change the library (no menu).
 * @param sort The current sort.
 * @param onSort Called with a sortable column's key on a header click.
 * @param selection The row selection for the bulk move, or `undefined` where the person may not change the library.
 * @param onShowUsage Opens the usage dialog.
 * @param emptyState Shown instead of the table when there is no row.
 * @param total Rows matching the filters, for "Show more".
 * @param onLoadMore Loads the next page.
 */
export function SymbolLibraryTable({
  rows, urlFor, organizationLabel, actions, sort, onSort, selection, onShowUsage, emptyState, total, onLoadMore,
}: {
  rows: SymbolLibraryRow[];
  urlFor: (id: string) => string;
  organizationLabel: string;
  actions: SymbolRowActionContext | null;
  sort: SortState | null;
  onSort: (key: string) => void;
  selection?: DirectoryTableSelection<SymbolLibraryRow>;
  onShowUsage: (row: SymbolLibraryRow) => void;
  emptyState: ReactNode;
  total: number;
  onLoadMore: () => void;
}) {
  const columns: DirectoryColumn<SymbolLibraryRow>[] = [
    { key: "preview", label: <span className="sr-only">Drawing</span>, render: (r) => <SymbolImage src={urlFor(r.id)} alt={`Drawing of ${r.name}`} /> },
    {
      key: "name", label: "Name", sortable: true,
      render: (r) => (
        <span className="row" style={{ gap: "var(--space-2)", flexWrap: "nowrap", alignItems: "center", minWidth: 0 }}>
          <CellText lines={2}>{r.name}</CellText>
          <SymbolBadges row={r} organizationLabel={organizationLabel} inProject={actions?.inProject ?? false} />
        </span>
      ),
    },
    { key: "source", label: "Source", sortable: true, render: sourceText },
    { key: "folder", label: "Folder", sortable: true, render: (r) => (r.folder_path ? <CellText lines={2}>{r.folder_path}</CellText> : <span className="text-muted">—</span>) },
    { key: "used", label: "Used by", render: (r) => <UsedBy row={r} onShow={onShowUsage} /> },
  ];
  if (actions) {
    columns.push({
      key: "actions", label: <span className="sr-only">Actions</span>,
      render: (r) => <ActionMenu triggerLabel={`Actions for ${r.name}`} items={symbolRowActions(r, actions)} />,
    });
  }
  return (
    <DirectoryTable
      ariaLabel="Symbols" columns={columns} rows={rows} rowKey={(r) => r.id} sort={sort} onSort={onSort}
      selection={selection} emptyState={emptyState} total={total} onLoadMore={onLoadMore}
    />
  );
}
