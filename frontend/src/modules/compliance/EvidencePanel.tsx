/**
 * Module: modules/compliance/EvidencePanel
 *
 * The project's supporting-evidence library (§13-§15), project-scoped rather than nested under one standard assignment, since
 * one piece of evidence may support requirements across several assignments. A `DirectoryTable` + `FilterPanel` list (style
 * guide "Pattern: directories at scale") with a `Modal` create flow. A row links to `EvidenceDetailPage` (files, links,
 * revalidation, archive): evidence carries attachments and a Links panel, so it is a page, not a `SidePanel`. Linking evidence
 * to a requirement is done from `RequirementAssessmentPanel` ("Link existing evidence", "Upload new evidence" reusing
 * `EvidenceFormModal`); this panel is the canonical list and create surface, not a second place to manage linkage.
 */
import { useState } from "react";

import { RecordCode } from "../../components/RecordCode";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterPanel } from "../../components/FilterPanel";
import { ListActions } from "../../components/ListActions";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import { EvidenceFormModal } from "./EvidenceFormModals";
import { COMPLIANCE_EVIDENCE_VALIDITY_STATE_LABEL, type ComplianceEvidence } from "./types";
import { useCommitQuickLinks } from "../../hooks/useCommitQuickLinks";
import { useCommitTags } from "../../hooks/useCommitTags";
import { useCreatedToast } from "../../hooks/useCreatedToast";
import { useOptionalColumns } from "../../hooks/useOptionalColumns";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { addSortParams, TIME_SORT_KEYS, useListSort } from "../../hooks/useListSort";
import { SortField } from "../../components/SortField";
import { sortRows, TIME_SORT_VALUES, type SortValue } from "../../utils/sortRows";
import { evidencePath } from "./paths";

const NO_EVIDENCE: ComplianceEvidence[] = [];

/** Sortable value of each sortable column; the same text the cell shows, so the order matches what is read. */
const EVIDENCE_SORT_KEYS = ["title", "code", "issuing_organisation", "expiry_date", "validity", "status", ...TIME_SORT_KEYS] as const;
const EVIDENCE_SORT_VALUES: Record<string, (e: ComplianceEvidence) => SortValue> = {
  ...TIME_SORT_VALUES,
  title: (e) => e.title,
  code: (e) => e.unique_code,
  issuing_organisation: (e) => e.issuing_organisation,
  expiry_date: (e) => e.expiry_date,
  validity: (e) => COMPLIANCE_EVIDENCE_VALIDITY_STATE_LABEL[e.validity_state],
  status: (e) => (e.is_archived ? "Archived" : "Active"),
};

/**
 * The evidence list for one project, with search, a "Show archived" filter and the Add evidence dialog.
 *
 * @param projectId The project whose evidence is listed.
 */
export function EvidencePanel({ projectId }: { projectId: string }) {
  const { showToast } = useToast();
  const commitQuickLinks = useCommitQuickLinks(projectId, "compliance_evidence");
  const commitTags = useCommitTags(projectId, "compliance_evidence");
  const announceCreated = useCreatedToast(projectId, "compliance_evidence");
  const [evidence, setEvidence] = useState<ComplianceEvidence[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [creating, setCreating] = useState(false);

  async function reload() {
    try {
      setEvidence(await complianceApi.listEvidence(projectId));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "Could not load evidence."));
    }
  }

  useLoadOnChange(reload, [projectId]);

  /** The list's filters by the names its export takes; the server applies the same rules the page does. */
  function filterParams(): URLSearchParams {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (includeArchived) params.set("include_archived", "true");
    return addSortParams(params, listSort.sort);
  }

  const listSort = useListSort("compliance_evidence", EVIDENCE_SORT_KEYS, "code", true);
  const sortedRows = sortRows(evidence ?? NO_EVIDENCE, listSort.sort, EVIDENCE_SORT_VALUES);
  const columns: DirectoryColumn<ComplianceEvidence>[] = [
    { key: "title", label: "Title", sortable: true, render: (e) => e.title },
    { key: "code", label: "Code", sortable: true, render: (e) => <RecordCode code={e.unique_code} /> },
    { key: "issuing_organisation", label: "Issuing organisation", sortable: true, optional: true, render: (e) => e.issuing_organisation ?? "—" },
    { key: "expiry_date", label: "Expiry", sortable: true, optional: true, render: (e) => e.expiry_date ?? "—" },
    { key: "validity", label: "Validity", sortable: true, optional: true, render: (e) => COMPLIANCE_EVIDENCE_VALIDITY_STATE_LABEL[e.validity_state] },
    { key: "status", label: "Status", sortable: true, render: (e) => (e.is_archived ? "Archived" : "Active") },
  ];

  const shown = useOptionalColumns("compliance_evidence", columns);

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (evidence === null) return <Spinner />;

  const filtered = sortedRows
    .filter((e) => includeArchived || !e.is_archived)
    .filter((e) => !search || `${e.unique_code} ${e.title}`.toLowerCase().includes(search.toLowerCase()));

  return (
    <div className="stack">
      <div className="row" style={{ gap: "var(--space-3)", alignSelf: "flex-start" }}>
        <button className="btn btn-primary" onClick={() => setCreating(true)}>
          Add evidence
        </button>
        <ListActions projectId={projectId} recordType="compliance_evidence" filters={filterParams().toString()} onImported={reload} />
        {shown.chooser}
      </div>
      <div className="side-grid">
        <DirectoryTable
          ariaLabel="Compliance evidence"
          columns={shown.columns}
          rows={filtered}
          sort={listSort.sort}
          onSort={listSort.onHeaderSort}
          rowKey={(e) => e.id}
          placements={{ projectId, artefactType: "compliance_evidence", rowId: (e) => e.id }}
          rowHref={(e) => evidencePath(projectId, e.id)}
          emptyState={<p className="text-muted">No evidence recorded for this project yet.</p>}
        />
        <FilterPanel
          sectionKey="compliance.evidence" total={evidence.length} matching={filtered.length}
          search={search} onSearchChange={setSearch} searchPlaceholder="Search evidence…" searchAriaLabel="Search evidence"
        >
          <SortField list={listSort} columns={columns} titleKey="title" />
          <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
        </FilterPanel>
      </div>

      {creating && (
        <EvidenceFormModal
          projectId={projectId}
          onCancel={() => setCreating(false)}
          onSave={async (values, files, quickLinks, tags) => {
            try {
              const created = await complianceApi.createEvidence(projectId, values);
              for (const file of files) {
                await complianceApi.uploadEvidenceAttachment(projectId, created.id, file);
              }
              announceCreated("Evidence", created, files.length > 0 ? "created and file(s) attached" : "created");
              setCreating(false);
              await commitQuickLinks(created.id, quickLinks);
              await commitTags(created.id, tags);
              await reload();
            } catch (err) {
              showToast(toErrorMessage(err, "Could not create evidence."), "error");
            }
          }}
        />
      )}
    </div>
  );
}
