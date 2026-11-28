/**
 * Module: modules/traceability/ProjectExceptionsPage
 *
 * A project's traceability exceptions (`/projects/:projectId/modules/traceability/exceptions`): each with its record,
 * the rule it excepts, its approval state and whether it covers the record today. A row links to
 * `ExceptionDetailPage` in the row's own project. The list reads only; it exports and imports through the shared list
 * actions, and has no creation control.
 */
import { useState } from "react";
import { useParams } from "react-router-dom";

import { rowProjectId } from "../../api/projectScope";
import { Badge } from "../../components/Badge";
import { CellText } from "../../components/CellText";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterPanel } from "../../components/FilterPanel";
import { FilterSelect } from "../../components/FilterSelect";
import { ListPageLayout } from "../../components/ListPageLayout";
import { PrincipalBadge } from "../../components/PrincipalBadge";
import { ProjectScopeFilter } from "../../components/ProjectScopeFilter";
import { ProjectScopeLabel } from "../../components/ProjectScopeLabel";
import { RecordCode } from "../../components/RecordCode";
import { SortField } from "../../components/SortField";
import { Spinner } from "../../components/Spinner";
import { TagFilterField } from "../../components/TagFilterField";
import { useStrings } from "../../context/TerminologyContext";
import { toErrorMessage } from "../../context/ToastContext";
import { addSortParams, TIME_SORT_KEYS, useListSort } from "../../hooks/useListSort";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useOptionalColumns } from "../../hooks/useOptionalColumns";
import { useProjectScope } from "../../hooks/useProjectScope";
import { useTagFilter } from "../../hooks/useTagFilter";
import { useUrlChoice, useUrlFlag, useUrlText } from "../../hooks/useUrlFilter";
import { labelOptions } from "../../utils/labelOptions";
import { addSharedListFilters } from "../../utils/listFilterParams";
import { sortRows, TIME_SORT_VALUES } from "../../utils/sortRows";
import { exceptionApi } from "./exceptionApi";
import { EXCEPTION_HELP } from "./help";
import { exceptionCoverLabel, EXCEPTION_STATUS_LABEL, EXCEPTION_STATUS_TONE } from "./types";
import type { ExceptionStatus, TraceabilityException } from "./types";

const SORT_KEYS = [
  "unique_code", "title", "record", "record_type", "rule", "status", "covers", "expires_on", "review_date", "requester",
  ...TIME_SORT_KEYS,
] as const;

export function ProjectExceptionsPage() {
  const strings = useStrings();
  const { projectId } = useParams<{ projectId: string }>();
  const [exceptions, setExceptions] = useState<TraceabilityException[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Filters live in the URL so the list comes back as it was left after a visit to a record.
  const [search, setSearch] = useUrlText("q");
  const [statusFilter, setStatusFilter] = useUrlChoice("status", Object.keys(EXCEPTION_STATUS_LABEL) as ExceptionStatus[]);
  const [openOnly, setOpenOnly] = useUrlFlag("open");
  const [includeArchived, setIncludeArchived] = useUrlFlag("archived");
  const listSort = useListSort("traceability_exceptions", SORT_KEYS, "unique_code");
  const tagFilter = useTagFilter();
  const projectScope = useProjectScope(projectId);

  async function reload() {
    if (!projectId) return;
    try {
      setExceptions(await exceptionApi.list(projectId, {
        status: statusFilter || undefined,
        include_archived: includeArchived,
        open_only: openOnly,
        ...tagFilter.listFilters,
        project_scope: projectScope.scope,
      }));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "Traceability exceptions are not enabled for this project, or you do not have access to them."));
    }
  }

  useLoadOnChange(reload, [projectId, statusFilter, includeArchived, openOnly, tagFilter.query, projectScope.scope]);

  /** The list's filters by the names its export takes. */
  function filterParams(): URLSearchParams {
    const params = new URLSearchParams();
    if (statusFilter) params.set("status", statusFilter);
    if (search) params.set("search", search);
    if (includeArchived) params.set("include_archived", "true");
    if (openOnly) params.set("open_only", "true");
    addSharedListFilters(params, tagFilter, projectScope);
    addSortParams(params, listSort.sort);
    return params;
  }

  const columns: DirectoryColumn<TraceabilityException>[] = [
    { key: "unique_code", label: "Code", sortable: true, render: (e) => <RecordCode code={e.unique_code} ownerProjectCode={e.from_project_code} /> },
    { key: "title", label: "Title", sortable: true, render: (e) => <><CellText lines={2}>{e.title}</CellText><ProjectScopeLabel row={e} /></> },
    {
      key: "record", label: "Record", sortable: true,
      render: (e) => (e.record.code ? <CellText lines={2}>{`${e.record.code} ${e.record.label}`}</CellText> : "Removed"),
    },
    { key: "record_type", label: "Record type", sortable: true, optional: true, defaultHidden: true, render: (e) => e.record.artefact_type_label },
    { key: "rule", label: "Rule", sortable: true, optional: true, render: (e) => <CellText lines={2}>{e.rule_name}</CellText> },
    {
      key: "status", label: "Status", sortable: true,
      render: (e) => <Badge tone={EXCEPTION_STATUS_TONE[e.status]}>{EXCEPTION_STATUS_LABEL[e.status]}</Badge>,
    },
    {
      key: "covers", label: "Cover", sortable: true, optional: true,
      render: (e) => <Badge tone={e.covers ? "accent" : "muted"}>{exceptionCoverLabel(e)}</Badge>,
    },
    { key: "expires_on", label: "Expiry date", sortable: true, optional: true, render: (e) => e.expires_on ?? "—" },
    { key: "review_date", label: "Review date", sortable: true, optional: true, defaultHidden: true, render: (e) => e.review_date ?? "—" },
    { key: "requester", label: "Requester", sortable: true, optional: true, render: (e) => <PrincipalBadge principal={e.requester} /> },
  ];

  const shown = useOptionalColumns("traceability_exceptions_list", columns);

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (exceptions === null) return <Spinner />;

  const needle = search.trim().toLowerCase();
  const rows = needle
    ? exceptions.filter((e) => `${e.unique_code} ${e.title} ${e.rule_name} ${e.record.code} ${e.record.label} ${e.reason}`.toLowerCase().includes(needle))
    : exceptions;
  const sorted = sortRows(rows, listSort.sort, {
    ...TIME_SORT_VALUES,
    unique_code: (e) => e.unique_code,
    title: (e) => e.title,
    record: (e) => e.record.code || null,
    record_type: (e) => e.record.artefact_type_label,
    rule: (e) => e.rule_name,
    status: (e) => EXCEPTION_STATUS_LABEL[e.status],
    covers: (e) => exceptionCoverLabel(e),
    expires_on: (e) => e.expires_on,
    review_date: (e) => e.review_date,
    requester: (e) => e.requester?.label ?? null,
  });

  return (
    <div className="container stack">
      <ListPageLayout
        title="Traceability Exceptions"
        columnChooser={shown.chooser}
        records={{ projectId, recordType: "traceability_exception", filters: filterParams().toString(), onImported: reload }}
        filter={
          <FilterPanel
            sectionKey="traceability.exceptions" total={rows.length}
            search={search} onSearchChange={setSearch} searchPlaceholder="Search exceptions…" searchAriaLabel="Search exceptions"
          >
            <FilterSelect
              label={strings.filters.status}
              value={statusFilter}
              onChange={setStatusFilter}
              allLabel="All statuses"
              options={labelOptions(EXCEPTION_STATUS_LABEL)}
            />
            <FilterCheckbox label="Open only" help={EXCEPTION_HELP.openOnly} checked={openOnly} onChange={setOpenOnly} />
            <ProjectScopeFilter scope={projectScope} />
            <TagFilterField projectId={projectId} filter={tagFilter} />
            <SortField list={listSort} columns={columns} codeKey="unique_code" />
            <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
          </FilterPanel>
        }
      >
        <DirectoryTable
          ariaLabel="Traceability exceptions"
          columns={shown.columns}
          rows={sorted}
          sort={listSort.sort}
          onSort={listSort.onHeaderSort}
          rowKey={(e) => e.id}
          placements={{ projectId, artefactType: "traceability_exception", rowId: (e) => e.id }}
          rowHref={(e) => `/projects/${rowProjectId(e, projectId)}/modules/traceability/exceptions/${e.id}`}
          emptyState={
            <p className="text-muted">
              {exceptions.length > 0 || statusFilter || openOnly
                ? "No exceptions match these filters."
                : "No traceability exceptions recorded for this project yet."}
            </p>
          }
        />
      </ListPageLayout>
    </div>
  );
}
