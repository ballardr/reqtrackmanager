/**
 * Module: modules/stakeholders/RecordListView
 *
 * The list shared by every record kind in this module (Persona, Stakeholder, Need, Engagement),
 * on both the project page and the organisation panel: the `DirectoryTable` +
 * `FilterPanel` + "New …" `Modal` shape every module artefact list uses, with
 * status and type filters and the standard archived toggle. What differs per
 * kind is passed in — the noun, the kind-specific columns, the create form —
 * rather than copied into a second list. A kind with no lifecycle (an
 * Engagement) passes no `statusLabel`/`statusTone` and no archived toggle, and
 * a kind whose "type" has another name (an Engagement's channel) passes
 * `typeLabel`.
 *
 * Status, type and scope render through their label maps; status and type
 * badges are `FilterBadge`s because the same page filters on both (style
 * guide principle 10). The Name, Type, Scope and Status columns are fixed
 * (Type and Scope are left out for a kind without them, e.g. a project-only
 * Need: pass no `typeName`/`scopeLabels`); `columnsBeforeType` and
 * `columnsAfterScope` slot the kind's own columns around them.
 *
 * A kind can add its own filters (`extraFilters`) and narrow `records` before
 * passing them in (Stakeholders do both for groups, Phase 3c).
 *
 * Per-project visibility (Phase 3b): a page that lets the project hide org
 * records passes `onIncludeHiddenChange` for a "Show hidden" filter and
 * `onShowHidden`, which adds a Visibility column to a hidden row stating who
 * hid it and offering "Show". A hidden row is not openable (the project API
 * treats a hidden record as absent), so `onOpen` is skipped for it.
 */
import { useState, type ReactNode } from "react";

import type { BadgeTone } from "../../api/types";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterBadge } from "../../components/FilterBadge";
import { FilterCheckbox, FilterField, FilterPanel } from "../../components/FilterPanel";
import { toErrorMessage } from "../../context/ToastContext";
import { HIDDEN_SOURCE_LABEL, type HiddenSource } from "./types";

/** What the list needs of any record kind. */
export interface ListedRecord {
  id: string;
  name: string;
  /** Omit for a kind with no lifecycle. */
  status?: string;
  scope?: string;
  /** Set only by project endpoints, for an org record: whether the project hides it. */
  project_hidden?: boolean | null;
  hidden_source?: HiddenSource | null;
}

export function RecordListView<R extends ListedRecord, V>({
  records,
  ariaLabel,
  sectionKey,
  noun,
  newLabel,
  scopeLabel,
  emptyText,
  showScope,
  statusLabel,
  statusTone,
  scopeLabels,
  typeName,
  typeLabel = "Type",
  searchText,
  columnsBeforeType,
  columnsAfterScope,
  toolbar,
  extraFilters,
  includeArchived = false,
  onIncludeArchivedChange,
  includeHidden = false,
  onIncludeHiddenChange,
  onShowHidden,
  onOpen,
  onCreate,
  renderCreateModal,
}: {
  records: R[];
  ariaLabel: string;
  sectionKey: string;
  /** Singular noun for the New button and search placeholder, e.g. "Persona". */
  noun: string;
  /** The create button's text; defaults to "New {noun}". */
  newLabel?: string;
  /** "project" / "organisation", passed to the create modal. */
  scopeLabel: string;
  emptyText: string;
  showScope: boolean;
  /** Omit (with `statusTone`) for a kind with no status: the Status column and filter are left out. */
  statusLabel?: Record<string, string>;
  statusTone?: Record<string, BadgeTone>;
  /** Omit for a kind that has no scope. */
  scopeLabels?: Record<string, string>;
  /** Omit for a kind that has no type: the Type column and filter are left out. */
  typeName?: (record: R) => string | null;
  /** Heading and filter label of the type column; defaults to "Type". */
  typeLabel?: string;
  /** The text the search box matches against. */
  searchText: (record: R) => string;
  columnsBeforeType: DirectoryColumn<R>[];
  columnsAfterScope: DirectoryColumn<R>[];
  /** Extra controls beside the New button (e.g. "Add from org user"). */
  toolbar?: ReactNode;
  /** Extra `FilterField`s a kind adds to the filter panel (e.g. Stakeholders' group filter). */
  extraFilters?: ReactNode;
  includeArchived?: boolean;
  /** Offered when passed; omit for a kind that cannot be archived. */
  onIncludeArchivedChange?: (next: boolean) => void;
  includeHidden?: boolean;
  /** Offered on the project page only; omit where there is nothing to hide. */
  onIncludeHiddenChange?: (next: boolean) => void;
  /** Re-shows a hidden record in this project (the Visibility cell's "Show" action). */
  onShowHidden?: (record: R) => void;
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

  const typeNames = typeName ? Array.from(new Set(records.map(typeName).filter((n): n is string => !!n))).sort() : [];
  const filtered = records.filter((r) => {
    if (statusFilter && r.status !== statusFilter) return false;
    if (typeFilter && typeName?.(r) !== typeFilter) return false;
    if (search && !searchText(r).toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const columns: DirectoryColumn<R>[] = [
    { key: "name", label: "Name", render: (r) => r.name },
    ...columnsBeforeType,
    ...(typeName
      ? [{
          key: "type", label: typeLabel,
          render: (r: R) => {
            const name = typeName(r);
            return name ? (
              <FilterBadge active={typeFilter === name} onClick={() => setTypeFilter(typeFilter === name ? "" : name)}>
                {name}
              </FilterBadge>
            ) : "—";
          },
        } as DirectoryColumn<R>]
      : []),
    ...(showScope && scopeLabels
      ? [{ key: "scope", label: "Scope", render: (r: R) => (r.scope ? scopeLabels[r.scope] : "—") } as DirectoryColumn<R>]
      : []),
    ...columnsAfterScope,
    ...(includeHidden && onShowHidden
      ? [{
          key: "visibility", label: "Visibility",
          render: (r: R) =>
            r.project_hidden && r.hidden_source ? (
              <span className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
                <span className="badge">{HIDDEN_SOURCE_LABEL[r.hidden_source]}</span>
                <button className="btn" aria-label={`Show ${r.name} in this project`} onClick={() => onShowHidden(r)}>
                  Show
                </button>
              </span>
            ) : "—",
        } as DirectoryColumn<R>]
      : []),
    ...(statusLabel && statusTone
      ? [{
          key: "status", label: "Status",
          render: (r: R) =>
            r.status ? (
              <FilterBadge tone={statusTone[r.status]} active={statusFilter === r.status} onClick={() => setStatusFilter(statusFilter === r.status ? "" : (r.status ?? ""))}>
                {statusLabel[r.status]}
              </FilterBadge>
            ) : "—",
        } as DirectoryColumn<R>]
      : []),
  ];

  return (
    <div className="stack">
      <div className="row" style={{ gap: "0.5rem", alignSelf: "flex-start" }}>
        <button className="btn btn-primary" onClick={() => setCreating(true)}>
          {newLabel ?? `New ${noun}`}
        </button>
        {toolbar}
      </div>
      <div className="side-grid">
        <DirectoryTable
          ariaLabel={ariaLabel}
          columns={columns}
          rows={filtered}
          rowKey={(r) => r.id}
          onRowClick={(r) => { if (!r.project_hidden) onOpen(r); }}
          emptyState={<p className="text-muted">{emptyText}</p>}
        />
        <FilterPanel
          sectionKey={sectionKey} total={filtered.length}
          search={search} onSearchChange={setSearch} searchPlaceholder={`Search ${noun}s…`} searchAriaLabel={`Search ${ariaLabel}`}
        >
          {statusLabel && (
            <FilterField label="Status">
              <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                <option value="">All statuses</option>
                {Object.entries(statusLabel).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </FilterField>
          )}
          {typeName && (
            <FilterField label={typeLabel}>
              <select className="input" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
                <option value="">{typeLabel === "Type" ? "All types" : `All ${typeLabel.toLowerCase()}s`}</option>
                {typeNames.map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
            </FilterField>
          )}
          {extraFilters}
          {onIncludeArchivedChange && (
            <FilterCheckbox label="Show archived" checked={includeArchived} onChange={onIncludeArchivedChange} />
          )}
          {onIncludeHiddenChange && (
            <FilterCheckbox label="Show hidden" checked={includeHidden} onChange={onIncludeHiddenChange} />
          )}
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
