/**
 * Module: modules/architecture/SymbolUsageModal
 *
 * The dialog that shows where one symbol is used, opened from the Used by column of the symbol library so the full answer is
 * not a permanent part of the page. Lists each owner (a project, the organisation, or the projects the person cannot open
 * together) with how many element types and elements use the symbol and the element type names. Element names are never
 * listed: an element may be restricted, so the server returns counts only.
 */
import { useEffect, useState } from "react";

import { CellText } from "../../components/CellText";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { Modal } from "../../components/Modal";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage } from "../../context/ToastContext";
import { useTableSort } from "../../hooks/useTableSort";
import { symbolApi } from "./api";
import type { TypesScope } from "./ArchitectureTypesPanel";
import type { SymbolLibraryRow, SymbolUsage, SymbolUsageOwner } from "./types";

const NO_OWNERS: SymbolUsageOwner[] = [];

/** The sortable value of each sortable column. */
const OWNER_SORT_VALUES = {
  owner: (o: SymbolUsageOwner) => o.name,
  types: (o: SymbolUsageOwner) => o.element_type_count,
  elements: (o: SymbolUsageOwner) => o.element_count,
};

/** "1 element type" / "3 element types" and the like. */
function count(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

/**
 * @param scope The project or organisation whose library the symbol is read through.
 * @param symbol The symbol whose use is shown.
 * @param onClose Closes the dialog.
 */
export function SymbolUsageModal({ scope, symbol, onClose }: { scope: TypesScope; symbol: SymbolLibraryRow; onClose: () => void }) {
  const [usage, setUsage] = useState<SymbolUsage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const scopeId = scope.kind === "project" ? scope.projectId : scope.organizationId;

  useEffect(() => {
    let live = true;
    (scope.kind === "project" ? symbolApi.projectUsage(scopeId, symbol.id) : symbolApi.orgUsage(scopeId, symbol.id))
      .then((found) => { if (live) setUsage(found); })
      .catch((err) => { if (live) setError(toErrorMessage(err, "Could not load where the symbol is used.")); });
    return () => { live = false; };
  }, [scope.kind, scopeId, symbol.id]);

  const table = useTableSort(usage?.owners ?? NO_OWNERS, OWNER_SORT_VALUES);
  const columns: DirectoryColumn<SymbolUsageOwner>[] = [
    { key: "owner", label: "Used by", sortable: true, render: (o) => <CellText lines={2}>{o.name}</CellText> },
    { key: "types", label: "Element types", sortable: true, render: (o) => (o.element_type_count === 0 ? "—" : o.element_types.length > 0 ? `${count(o.element_type_count, "element type")}: ${o.element_types.join(", ")}` : count(o.element_type_count, "element type")) },
    { key: "elements", label: "Elements", sortable: true, render: (o) => (o.element_count === 0 ? "—" : count(o.element_count, "element")) },
  ];

  return (
    <Modal title={`Where ${symbol.name} is used`} onClose={onClose} size="lg">
      {error ? <div role="alert" style={{ color: "var(--color-danger)" }}>{error}</div>
        : usage === null ? <Spinner />
          : (
            <DirectoryTable
              ariaLabel={`Where ${symbol.name} is used`} columns={columns} rows={table.rows} rowKey={(o) => `${o.kind}:${o.name}`}
              sort={table.sort} onSort={table.onSort}
              emptyState={<p className="text-muted">No element type or element uses this symbol.</p>}
            />
          )}
    </Modal>
  );
}
