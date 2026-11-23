const NONE: GuidingPrinciple[] = [];

/**
 * Module: modules/context_strategy/OrgGuidingPrinciplesPanel
 *
 * The organisation-scoped equivalent of `ProjectGuidingPrinciplesPage.tsx`: an organisation's own Guiding Principle
 * records, rendered as an `OrgResourcesPage.tsx` `ResourceMenu` group (`module.ts`'s `orgResourceSections`). Placement
 * follows `OrgStrategiesPanel.tsx`. Pain Point Type is a configuration table with no organisation-scoped record, so it
 * is an `orgAdminSections` entry instead.
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ListActions } from "../../components/ListActions";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterPanel } from "../../components/FilterPanel";
import { FilterSelect } from "../../components/FilterSelect";
import { ScopedRecordCode } from "../../components/ScopedRecordCode";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { GUIDING_PRINCIPLE_SORT_KEYS, GUIDING_PRINCIPLE_SORT_VALUES } from "./contextStrategySort";
import { orgGuidingPrincipleApi } from "./api";
import { GuidingPrincipleFormModal } from "./GuidingPrincipleFormModal";
import { GUIDING_PRINCIPLE_PRIORITY_LABEL, GUIDING_PRINCIPLE_STATUS_LABEL, GUIDING_PRINCIPLE_STATUS_TONE } from "./types";
import type { GuidingPrinciple, GuidingPrincipleFieldValues, GuidingPrinciplePriority, GuidingPrincipleStatus } from "./types";
import { Badge } from "../../components/Badge";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useListSort } from "../../hooks/useListSort";
import { SortField } from "../../components/SortField";
import { sortRows } from "../../utils/sortRows";
import { filterStringWithSort } from "../../utils/listFilterParams";
import { useStrings } from "../../context/TerminologyContext";
import { labelOptions } from "../../utils/labelOptions";

export function OrgGuidingPrinciplesPanel({ orgId }: { orgId: string }) {
  const strings = useStrings();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [guidingPrinciples, setGuidingPrinciples] = useState<GuidingPrinciple[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<GuidingPrincipleStatus | "">("");
  const [priorityFilter, setPriorityFilter] = useState<GuidingPrinciplePriority | "">("");
  const [includeArchived, setIncludeArchived] = useState(false);

  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function reloadGuidingPrinciples() {
    try {
      setGuidingPrinciples(await orgGuidingPrincipleApi.list(orgId, { include_archived: includeArchived }));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "The Context & Strategy module is not enabled for this organisation, or you do not have access to it."));
    }
  }

  useLoadOnChange(reloadGuidingPrinciples, [orgId, includeArchived]);

  const listSort = useListSort("org_guiding_principles", GUIDING_PRINCIPLE_SORT_KEYS, "code", true);
  const sortedRows = sortRows(guidingPrinciples ?? NONE, listSort.sort, GUIDING_PRINCIPLE_SORT_VALUES);
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (guidingPrinciples === null) return <Spinner />;

  const filtered = sortedRows.filter((g) => {
    if (statusFilter && g.status !== statusFilter) return false;
    if (priorityFilter && g.priority !== priorityFilter) return false;
    if (search && !`${g.unique_code} ${g.name}`.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const columns: DirectoryColumn<GuidingPrinciple>[] = [
    { key: "name", label: "Name", sortable: true, render: (g) => g.name },
    { key: "code", label: "Code", sortable: true, render: (g) => <span className="text-muted"><ScopedRecordCode record={g} /></span> },
    { key: "priority", label: "Priority", sortable: true, render: (g) => GUIDING_PRINCIPLE_PRIORITY_LABEL[g.priority] },
    {
      key: "status", label: "Status", sortable: true,
      render: (g) => <Badge tone={GUIDING_PRINCIPLE_STATUS_TONE[g.status]}>{GUIDING_PRINCIPLE_STATUS_LABEL[g.status]}</Badge>,
    },
    { key: "version", label: "Version", sortable: true, render: (g) => `v${g.version_number}` },
  ];

  return (
    <div className="stack">
      <div className="row" style={{ gap: "var(--space-3)", alignSelf: "flex-start" }}>
        <button className="btn btn-primary" onClick={() => setCreating(true)}>
          New Guiding Principle
        </button>
        <ListActions
          organizationId={orgId} recordType="guiding_principle" filters={filterStringWithSort({ status: statusFilter, priority: priorityFilter, search, include_archived: includeArchived }, listSort.sort)} onImported={reloadGuidingPrinciples}
        />
      </div>
      <div className="side-grid">
        <DirectoryTable
          ariaLabel="Organisation Guiding Principles"
          columns={columns}
          rows={filtered}
          sort={listSort.sort}
          onSort={listSort.onHeaderSort}
          rowKey={(g) => g.id}
          onRowClick={(g) => navigate(`/orgs/${orgId}/modules/context_strategy/guiding-principles/${g.id}`)}
          emptyState={<p className="text-muted">No organisation-scoped Guiding Principle recorded yet.</p>}
        />
        <FilterPanel
          sectionKey="context_strategy.orgGuidingPrinciples.list" total={filtered.length}
          search={search} onSearchChange={setSearch} searchPlaceholder="Search Guiding Principles…" searchAriaLabel="Search organisation Guiding Principles"
        >
          <FilterSelect
            label={strings.filters.status}
            value={statusFilter}
            onChange={setStatusFilter}
            allLabel="All statuses"
            options={labelOptions(GUIDING_PRINCIPLE_STATUS_LABEL)}
          />
          <FilterSelect
            label={strings.filters.priority}
            value={priorityFilter}
            onChange={setPriorityFilter}
            allLabel="All priorities"
            options={labelOptions(GUIDING_PRINCIPLE_PRIORITY_LABEL)}
          />
          <SortField list={listSort} columns={columns} titleKey="name" />
          <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
        </FilterPanel>
      </div>

      {creating && (
        <GuidingPrincipleFormModal
          scopeLabel="organisation"
          error={createError}
          onCancel={() => { setCreating(false); setCreateError(null); }}
          onSave={async (values: GuidingPrincipleFieldValues) => {
            setCreateError(null);
            try {
              await orgGuidingPrincipleApi.create(orgId, values);
              showToast("Guiding Principle created.");
              setCreating(false);
              await reloadGuidingPrinciples();
            } catch (err) {
              setCreateError(toErrorMessage(err, "Could not create Guiding Principle."));
            }
          }}
        />
      )}
    </div>
  );
}
