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
 * Export and Import (`exportRecords`): on a list page the layout offers the shared Export and Import of the kind,
 * narrowed by this list's own filters (status, type, search, archived, hidden, tags, scope) plus the `extraParams` the
 * kind adds (a group filter). A list embedded in another page (an organisation panel) offers neither.
 *
 * A kind can add its own filters (`extraFilters`) and narrow `records` before
 * passing them in. A list whose records are created elsewhere (the People page's "New" menu) omits
 * `onCreate`/`renderCreateModal`: it then shows no New button and no create form.
 *
 * Per-project visibility: a page that lets the project hide org
 * records passes `onIncludeHiddenChange` for a "Show hidden" filter and
 * `onShowHidden`, which adds a Visibility column to a hidden row stating who
 * hid it and offering "Show". A hidden row is not openable (the project API
 * treats a hidden record as absent), so `onOpen` is skipped for it.
 */
import type { CollectedLink } from "../../api/artefactLinks";
import { useState, type HTMLAttributes, type ReactNode } from "react";

import type { BadgeTone } from "../../api/types";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterBadge } from "../../components/FilterBadge";
import { ScopedRecordCode } from "../../components/ScopedRecordCode";
import { FilterCheckbox, FilterField, FilterPanel } from "../../components/FilterPanel";
import { ListPageLayout } from "../../components/ListPageLayout";
import { ProjectScopeFilter } from "../../components/ProjectScopeFilter";
import { ProjectScopeLabel } from "../../components/ProjectScopeLabel";
import { TagFilterField } from "../../components/TagFilterField";
import type { ProjectScopeState } from "../../hooks/useProjectScope";
import type { TagFilterState } from "../../hooks/useTagFilter";
import { useUrlText } from "../../hooks/useUrlFilter";
import { addSharedListFilters } from "../../utils/listFilterParams";
import { toErrorMessage } from "../../context/ToastContext";
import { HIDDEN_SOURCE_LABEL, type HiddenSource } from "./types";
import { Badge } from "../../components/Badge";

/** One record kind a list page offers Export and Import for. */
export interface ExportRecords {
  projectId: string;
  recordType: string;
  onImported?: () => void;
  /** Filters this kind adds beyond the list's own (a group filter). */
  extraParams?: Record<string, string>;
  /** Names the kind when the list shows several (`personas`). */
  kindLabel?: string;
  /** Filters this kind has no concept of: while one is set the kind has no rows to export, so it is not offered. */
  without?: ("status" | "type")[];
}

/** What the list needs of any record kind. */
/** The page-level header a list owns when it is a whole page: its title, actions and anything above the table. */
export interface RecordListPage {
  title: ReactNode;
  /** Replaces the list's own New button and toolbar when given. */
  actions?: ReactNode;
  /** A tab strip shown under the title; the list column is its panel (`contentProps`). */
  tabs?: ReactNode;
  contentProps?: HTMLAttributes<HTMLDivElement>;
  /** Chips or a switcher shown above the table in the list column. */
  above?: ReactNode;
}

export interface ListedRecord {
  id: string;
  name: string;
  /** The record's code (`PER-001`), shown as the Code column. */
  unique_code: string;
  /** Set for a record an organisation can own: qualifies the code of an organisation-owned one. */
  organization_id?: string | null;
  /** Omit for a kind with no lifecycle. */
  status?: string;
  scope?: string;
  /** Set only by project endpoints, for an org record: whether the project hides it. */
  project_hidden?: boolean | null;
  hidden_source?: HiddenSource | null;
  /** Set only on a row of a related project in a widened list. */
  from_project_id?: string | null;
  from_project_name?: string | null;
  from_project_code?: string | null;
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
  nameIcon,
  page,
  columnsBeforeType,
  columnsAfterScope,
  toolbar,
  extraFilters,
  tagFilter,
  projectScope,
  includeArchived = false,
  onIncludeArchivedChange,
  includeHidden = false,
  onIncludeHiddenChange,
  onShowHidden,
  onOpen,
  exportRecords,
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
  /** Page-level header (title, actions, tabs) shown in the list column so the filter panel starts at the title (`ListPageLayout`); omit for a list embedded in another page. */
  page?: RecordListPage;
  /** A kind icon shown before each name (`PeopleKindIcon`); omit for a list that has one kind. */
  nameIcon?: (record: R) => ReactNode;
  columnsBeforeType: DirectoryColumn<R>[];
  columnsAfterScope: DirectoryColumn<R>[];
  /** Extra controls beside the New button (e.g. "Add from org user"). */
  toolbar?: ReactNode;
  /** Extra `FilterField`s a kind adds to the filter panel (e.g. Stakeholders' group filter). */
  extraFilters?: ReactNode;
  /** Offers the project's tag filter; the page keeps the state (`useTagFilter`) and sends it with its list read. */
  tagFilter?: { projectId: string; filter: TagFilterState };
  /** The project page's list scope; offers the scope filter and labels rows of related projects. */
  projectScope?: ProjectScopeState;
  includeArchived?: boolean;
  /** Offered when passed; omit for a kind that cannot be archived. */
  onIncludeArchivedChange?: (next: boolean) => void;
  includeHidden?: boolean;
  /** Offered on the project page only; omit where there is nothing to hide. */
  onIncludeHiddenChange?: (next: boolean) => void;
  /** Re-shows a hidden record in this project (the Visibility cell's "Show" action). */
  onShowHidden?: (record: R) => void;
  onOpen: (record: R) => void;
  /** Offers the shared Export and Import of this kind on a list page (`page`); `extraParams` are the filters the kind adds. */
  exportRecords?: ExportRecords | ExportRecords[];
  /** Resolves on success; a rejection keeps the modal open and shows its message. Omit (with `renderCreateModal`) when records are created elsewhere. */
  onCreate?: (values: V, quickLinks: CollectedLink[], tags: string[]) => Promise<void>;
  /** Renders the create form; `onSave` is already wired to `onCreate` and the error state. */
  renderCreateModal?: (props: { scopeLabel: string; error: string | null; onCancel: () => void; onSave: (values: V, quickLinks?: CollectedLink[], tags?: string[]) => void }) => ReactNode;
}) {
  // On a list page the filters live in the URL, so it comes back as it was left after a visit to a record;
  // embedded in another page (an organisation panel) they stay local, leaving that page's own parameters alone.
  const [search, setSearch] = useUrlText("q", !!page);
  const [statusFilter, setStatusFilter] = useUrlText("status", !!page);
  const [typeFilter, setTypeFilter] = useUrlText("type", !!page);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const canCreate = !!onCreate && !!renderCreateModal;

  const typeNames = typeName ? Array.from(new Set(records.map(typeName).filter((n): n is string => !!n))).sort() : [];
  const filtered = records.filter((r) => {
    if (statusFilter && r.status !== statusFilter) return false;
    if (typeFilter && typeName?.(r) !== typeFilter) return false;
    if (search && !searchText(r).toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  /** The list's filters by the names the shared export takes (the server applies the same rules the list does). */
  function exportFilters(kind: ExportRecords): string {
    const params = new URLSearchParams(kind.extraParams);
    if (statusFilter) params.set("status", statusFilter);
    if (typeFilter) params.set("type", typeFilter);
    if (search) params.set("search", search);
    if (includeArchived) params.set("include_archived", "true");
    if (includeHidden) params.set("include_hidden", "true");
    return addSharedListFilters(params, tagFilter?.filter, projectScope).toString();
  }

  const exportActions = exportRecords
    ? [exportRecords].flat()
        .filter((kind) => !(kind.without ?? []).some((key) => (key === "status" ? statusFilter : typeFilter)))
        .map((kind) => ({ ...kind, filters: exportFilters(kind) }))
    : undefined;

  const columns: DirectoryColumn<R>[] = [
    { key: "name", label: "Name", render: (r) => <>{nameIcon && <span className="record-name-icon">{nameIcon(r)}</span>}{r.name}<ProjectScopeLabel row={r} /></> },
    { key: "code", label: "Code", render: (r) => <span className="text-muted"><ScopedRecordCode record={r} /></span> },
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
              <span className="row" style={{ gap: "var(--space-3)", alignItems: "center" }}>
                <Badge>{HIDDEN_SOURCE_LABEL[r.hidden_source]}</Badge>
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

  const newButton = canCreate && (
    <button className="btn btn-primary" onClick={() => setCreating(true)}>
      {newLabel ?? `New ${noun}`}
    </button>
  );
  const filterPanel = (
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
          {projectScope && <ProjectScopeFilter scope={projectScope} />}
          {tagFilter && <TagFilterField projectId={tagFilter.projectId} filter={tagFilter.filter} />}
          {onIncludeArchivedChange && (
            <FilterCheckbox label="Show archived" checked={includeArchived} onChange={onIncludeArchivedChange} />
          )}
          {onIncludeHiddenChange && (
            <FilterCheckbox label="Show hidden" checked={includeHidden} onChange={onIncludeHiddenChange} />
          )}
        </FilterPanel>
  );
  const table = (
        <DirectoryTable
          ariaLabel={ariaLabel}
          columns={columns}
          rows={filtered}
          rowKey={(r) => r.id}
          onRowClick={(r) => { if (!r.project_hidden) onOpen(r); }}
          emptyState={<p className="text-muted">{emptyText}</p>}
        />
  );

  return (
    <div className="stack">
      {page ? (
        <ListPageLayout
          title={page.title}
          actions={page.actions ?? ((newButton || toolbar) && <div className="row" style={{ gap: "var(--space-3)", alignSelf: "flex-start" }}>{newButton}{toolbar}</div>)}
          tabs={page.tabs}
          contentProps={page.contentProps}
          records={exportActions}
          filter={filterPanel}
        >
          {page.above}
          {table}
        </ListPageLayout>
      ) : (
        <>
          {(canCreate || toolbar) && (
            <div className="row" style={{ gap: "var(--space-3)", alignSelf: "flex-start" }}>
              {newButton}
              {toolbar}
            </div>
          )}
          <div className="side-grid">
            {table}
            {filterPanel}
          </div>
        </>
      )}

      {creating && onCreate && renderCreateModal &&
        renderCreateModal({
          scopeLabel,
          error: createError,
          onCancel: () => { setCreating(false); setCreateError(null); },
          onSave: async (values, quickLinks = [], tags = []) => {
            setCreateError(null);
            try {
              await onCreate(values, quickLinks, tags);
              setCreating(false);
            } catch (err) {
              setCreateError(toErrorMessage(err, `Could not create ${noun}.`));
            }
          },
        })}
    </div>
  );
}
