/**
 * Module: modules/compliance/EvidencePanel
 *
 * The project's supporting-evidence library (§13-§15) — project-scoped, not
 * nested under one standard assignment, since a single piece of evidence
 * may support requirements across more than one of a project's standard
 * assignments at once (§13's "multiple compliance requirements and/or
 * standards"). A `DirectoryTable` + `FilterPanel` list (style guide
 * "Pattern: directories at scale") and a `Modal` create flow (Principle 3).
 * A row links straight to `EvidenceDetailPage` (files, links, revalidation,
 * archive) — evidence carries attachments and a Links panel, so it is a page,
 * not a `SidePanel` (style guide "Pattern: entity detail panel").
 *
 * Linking evidence to a specific requirement/required-action assessment is
 * done from the requirement side (`RequirementAssessmentPanel`'s own
 * "Link existing evidence" control, plus the "Upload new evidence"
 * inline create-and-link flow, which reuses `EvidenceFormModals.tsx`'s
 * `EvidenceFormModal`) — this panel is the canonical evidence list and
 * create surface, not a second place to manage linkage.
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
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { evidencePath } from "./paths";

/**
 * The evidence list for one project, with search, a "Show archived" filter and the Add evidence dialog.
 *
 * @param projectId The project whose evidence is listed.
 */
export function EvidencePanel({ projectId }: { projectId: string }) {
  const { showToast } = useToast();
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
    return params;
  }

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (evidence === null) return <Spinner />;

  const filtered = evidence
    .filter((e) => includeArchived || !e.is_archived)
    .filter((e) => !search || `${e.unique_code} ${e.title}`.toLowerCase().includes(search.toLowerCase()));

  const columns: DirectoryColumn<ComplianceEvidence>[] = [
    { key: "title", label: "Title", render: (e) => e.title },
    { key: "code", label: "Code", render: (e) => <RecordCode code={e.unique_code} /> },
    { key: "issuing_organisation", label: "Issuing organisation", render: (e) => e.issuing_organisation ?? "—" },
    { key: "expiry_date", label: "Expiry", render: (e) => e.expiry_date ?? "—" },
    { key: "validity", label: "Validity", render: (e) => COMPLIANCE_EVIDENCE_VALIDITY_STATE_LABEL[e.validity_state] },
    { key: "status", label: "Status", render: (e) => (e.is_archived ? "Archived" : "Active") },
  ];

  return (
    <div className="stack">
      <div className="row" style={{ gap: "var(--space-3)", alignSelf: "flex-start" }}>
        <button className="btn btn-primary" onClick={() => setCreating(true)}>
          Add evidence
        </button>
        <ListActions projectId={projectId} recordType="compliance_evidence" filters={filterParams().toString()} onImported={reload} />
      </div>
      <div className="side-grid">
        <DirectoryTable
          ariaLabel="Compliance evidence"
          columns={columns}
          rows={filtered}
          rowKey={(e) => e.id}
          rowHref={(e) => evidencePath(projectId, e.id)}
          emptyState={<p className="text-muted">No evidence recorded for this project yet.</p>}
        />
        <FilterPanel
          sectionKey="compliance.evidence" total={evidence.length} matching={filtered.length}
          search={search} onSearchChange={setSearch} searchPlaceholder="Search evidence…" searchAriaLabel="Search evidence"
        >
          <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
        </FilterPanel>
      </div>

      {creating && (
        <EvidenceFormModal
          onCancel={() => setCreating(false)}
          onSave={async (values, files) => {
            try {
              const created = await complianceApi.createEvidence(projectId, values);
              for (const file of files) {
                await complianceApi.uploadEvidenceAttachment(projectId, created.id, file);
              }
              showToast(files.length > 0 ? "Evidence created and file(s) attached." : "Evidence created.");
              setCreating(false);
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
