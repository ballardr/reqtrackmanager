/**
 * Module: modules/stakeholders/RecordListView
 *
 * The list shared by every record kind in this module (Persona, Stakeholder),
 * on both the project page and the organisation panel: the `DirectoryTable` +
 * `FilterPanel` + "New …" `Modal` shape every module artefact list uses, with
 * status and type filters and the standard archived toggle. What differs per
 * kind is passed in — the noun, the kind-specific columns, the create form —
 * rather than copied into a second list.
 *
 * Status, type and scope render through their label maps; status and type
 * badges are `FilterBadge`s because the same page filters on both (style
 * guide principle 10). The Name, Type, Scope and Status columns are fixed;
 * `columnsBeforeType` and `columnsAfterScope` slot the kind's own columns
 * around them.
 */
import { useState, type ReactNode } from "react";

import type { BadgeTone } from "../../api/types";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterBadge } from "../../components/FilterBadge";
import { FilterCheckbox, FilterField, FilterPanel } from "../../components/FilterPanel";
import { toErrorMessage } from "../../context/ToastContext";

/** What the list needs of any record kind. */
export interface ListedRecord {
  id: string;
  name: string;
  status: string;
  scope: string;
}

export function RecordListView<R extends ListedRecord, V>({
  records,
  ariaLabel,
  sectionKey,
  noun,
  scopeLabel,
  emptyText,
  showScope,
  statusLabel,
  statusTone,
  scopeLabels,
  typeName,
  searchText,
  columnsBeforeType,
  columnsAfterScope,
  toolbar,
  includeArchived,
  onIncludeArchivedChange,
  onOpen,
  onCreate,
  renderCreateModal,
}: {
  records: R[];
  ariaLabel: string;
  sectionKey: string;
  /** Singular noun for the New button and search placeholder, e.g. "Persona". */
  noun: string;
  /** "project" / "organisation", passed to the create modal. */
  scopeLabel: string;
  emptyText: string;
  showScope: boolean;
  statusLabel: Record<string, string>;
  statusTone: Record<string, BadgeTone>;
  scopeLabels: Record<string, string>;
  typeName: (record: R) => string | null;
  /** The text the search box matches against. */
  searchText: (record: R) => string;
  columnsBeforeType: DirectoryColumn<R>[];
  columnsAfterScope: DirectoryColumn<R>[];
  /** Extra controls beside the New button (e.g. "Add from org user"). */
  toolbar?: ReactNode;
  includeArchived: boolean;
  onIncludeArchivedChange: (next: boolean) => void;
  onOpen: (record: R) => void;
  /** Resolves on success; a rejection keeps the modal open and shows its message. */
  onCreate: (values: V) => Promise<void>;
  /** Renders the create form; `onSave` is already wired to `onCreate` and the error state. */
  renderCreateModal: (props: { scopeLabel: string; error: string | null; onCancel: () => void; onSave: (values: V) => void }) => ReactNode;
}) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const typeNames = Array.from(new Set(records.map(typeName).filter((n): n is string => !!n))).sort();
  const filtered = records.filter((r) => {
    if (statusFilter && r.status !== statusFilter) return false;
    if (typeFilter && typeName(r) !== typeFilter) return false;
    if (search && !searchText(r).toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const columns: DirectoryColumn<R>[] = [
    { key: "name", label: "Name", render: (r) => r.name },
    ...columnsBeforeType,
    {
      key: "type", label: "Type",
      render: (r) => {
        const name = typeName(r);
        return name ? (
          <FilterBadge active={typeFilter === name} onClick={() => setTypeFilter(typeFilter === name ? "" : name)}>
            {name}
          </FilterBadge>
        ) : "—";
      },
    },
    ...(showScope ? [{ key: "scope", label: "Scope", render: (r: R) => scopeLabels[r.scope] } as DirectoryColumn<R>] : []),
    ...columnsAfterScope,
    {
      key: "status", label: "Status",
      render: (r) => (
        <FilterBadge tone={statusTone[r.status]} active={statusFilter === r.status} onClick={() => setStatusFilter(statusFilter === r.status ? "" : r.status)}>
          {statusLabel[r.status]}
        </FilterBadge>
      ),
    },
  ];

  return (
    <div className="stack">
      <div className="row" style={{ gap: "0.5rem", alignSelf: "flex-start" }}>
        <button className="btn btn-primary" onClick={() => setCreating(true)}>
          New {noun}
        </button>
        {toolbar}
      </div>
      <div className="side-grid">
        <DirectoryTable
          ariaLabel={ariaLabel}
          columns={columns}
          rows={filtered}
          rowKey={(r) => r.id}
          onRowClick={onOpen}
          emptyState={<p className="text-muted">{emptyText}</p>}
        />
        <FilterPanel
          sectionKey={sectionKey} total={filtered.length}
          search={search} onSearchChange={setSearch} searchPlaceholder={`Search ${noun}s…`} searchAriaLabel={`Search ${ariaLabel}`}
        >
          <FilterField label="Status">
            <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">All statuses</option>
              {Object.entries(statusLabel).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </FilterField>
          <FilterField label="Type">
            <select className="input" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
              <option value="">All types</option>
              {typeNames.map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
          </FilterField>
          <FilterCheckbox label="Show archived" checked={includeArchived} onChange={onIncludeArchivedChange} />
        </FilterPanel>
      </div>

      {creating &&
        renderCreateModal({
          scopeLabel,
          error: createError,
          onCancel: () => { setCreating(false); setCreateError(null); },
          onSave: async (values) => {
            setCreateError(null);
            try {
              await onCreate(values);
              setCreating(false);
            } catch (err) {
              setCreateError(toErrorMessage(err, `Could not create ${noun}.`));
            }
          },
        })}
    </div>
  );
}
