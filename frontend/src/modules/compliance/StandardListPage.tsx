/**
 * Module: modules/compliance/StandardListPage
 *
 * The cross-org "Compliance Standards" list (docs/compliance-module-plan.md
 * Phase 18) — the top-level `/standards` tab that promotes standards from
 * three clicks deep inside Org Admin to their own project-like nav entity,
 * modelled directly on `ProjectListPage.tsx`: same `.side-grid` (content
 * column first, `FilterPanel` second — `ProjectListPage.tsx`'s own order,
 * not `StandardsPanel.tsx`'s pre-Phase-18 backwards one, which this phase
 * doesn't carry forward), same `showOrgColumn` convention
 * (`orgs.length > 1 || !!user?.is_server_admin`), same Modal-based create
 * flow, same `GET /api/v1/orgs?mine=true` org-fetch pattern.
 *
 * No cross-org backend listing endpoint exists for standards — every
 * compliance route requires `organization_id` in the path (Phase 6's own
 * design). This page gets its rows via `complianceApi.listStandardsAcrossMyOrgs`,
 * the shared org-fan-out-and-collect helper (Phase 28 extracted it out of
 * this file so `StandardWorkspacePage.tsx`'s `EntitySwitcher` loader could
 * reuse the exact same fan-out/404-drop behaviour rather than duplicating
 * it) — see that function's own docstring in `./api.ts` for the full
 * 404-drop/error-swallow behaviour.
 *
 * "New standard" opens the same `StandardFormModal` `StandardWorkspacePage
 * .tsx` uses for editing, in create mode — an org picker (its own first
 * field, shown only when there's more than one candidate) precedes the
 * standard's own fields when the caller has more than one org to create in,
 * mirroring `ProjectListPage.tsx`'s "New project" org picker exactly. Each
 * row opens `/standards/:standardId`. A "Compliance settings" link per org
 * opens `/standards/settings/:orgId` (`ComplianceSettingsPage.tsx`).
 *
 * Phase 21 (standard-level import/export) replaces the plain "New standard"
 * button with a `SplitButtonTrigger`: the default action still opens
 * `StandardFormModal` unchanged, and a new "Import standard" alternative
 * opens `StandardImportModal` — the style guide's "one door" pattern
 * (Principle 5/11), grouping the rarer import path behind the same
 * trigger rather than a second, permanently-visible button competing with
 * "New standard".
 *
 * Phase 35a adds the `ViewToggle` tile/list split `docs/ux-style-guide.md`'s
 * "Pattern: view toggle" already requires of any list page like this one —
 * `ProjectListPage.tsx`'s own tile card is the direct precedent for the
 * tiles-mode render below (name + org + status, in card form).
 */
import { Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import type { Organization } from "../../api/types";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterPanel } from "../../components/FilterPanel";
import { SplitButtonTrigger } from "../../components/SplitButtonTrigger";
import { useViewMode, ViewToggle } from "../../components/ViewToggle";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import type { StandardAcrossOrgsRow } from "./api";
import { refreshComplianceNavVisibility } from "./useComplianceNavVisibility";
import { StandardFormModal, type EditableStandardFieldValues, type StandardFormValues } from "./StandardFormModal";
import { StandardImportModal } from "./StandardImportModal";
import type { StandardImportResult } from "./types";

type StandardListRow = StandardAcrossOrgsRow;

export function StandardListPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { showToast } = useToast();

  const [orgs, setOrgs] = useState<Organization[] | null>(null);
  const [rows, setRows] = useState<StandardListRow[] | null>(null);
  const [search, setSearch] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [viewMode, setViewMode] = useViewMode("standards");

  async function reload() {
    setRows(null);
    const { orgs: orgList, rows: collected } = await complianceApi.listStandardsAcrossMyOrgs(includeArchived);
    setOrgs(orgList);
    setRows(collected);
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [includeArchived]);

  const showOrgColumn = (orgs?.length ?? 0) > 1 || !!user?.is_server_admin;
  const filtered = (rows ?? []).filter(
    (s) => !search || s.name.toLowerCase().includes(search.toLowerCase()) || s.reference.toLowerCase().includes(search.toLowerCase())
  );

  const columns: DirectoryColumn<StandardListRow>[] = [
    { key: "reference", label: "Reference", sortable: false, render: (s) => s.reference },
    { key: "name", label: "Name", sortable: false, render: (s) => s.name },
    ...(showOrgColumn
      ? [{ key: "organisation", label: "Organisation", render: (s: StandardListRow) => s.organization_name } as DirectoryColumn<StandardListRow>]
      : []),
    { key: "issuing_organisation", label: "Issuing organisation", render: (s) => s.issuing_organisation ?? "—" },
    { key: "status", label: "Status", render: (s) => (s.is_archived ? "Archived" : "Active") },
  ];

  async function handleCreate(values: StandardFormValues | EditableStandardFieldValues, organizationId: string) {
    setCreateError(null);
    try {
      const standard = await complianceApi.createStandard(organizationId, values as StandardFormValues);
      showToast("Standard created.");
      setCreating(false);
      refreshComplianceNavVisibility();
      navigate(`/standards/${standard.id}`);
    } catch (err) {
      setCreateError(toErrorMessage(err, "Could not create standard."));
    }
  }

  function handleImported(result: StandardImportResult) {
    setImporting(false);
    if (result.skipped || !result.standard) {
      showToast("Import skipped.");
      return;
    }
    showToast(
      result.warnings.length > 0
        ? `Standard imported with ${result.warnings.length} warning(s) — see its history for details.`
        : "Standard imported."
    );
    refreshComplianceNavVisibility();
    void reload();
    navigate(`/standards/${result.standard.id}`);
  }

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>Compliance Standards</h1>
        <SplitButtonTrigger
          icon={<Plus size={16} />}
          label="New standard"
          onDefaultAction={() => setCreating(true)}
          menuTitle="New standard"
          moreOptionsLabel="More options"
          disabled={orgs === null}
          alternatives={[{ label: "Import standard", onSelect: () => setImporting(true) }]}
        />
      </div>

      {orgs && orgs.length > 0 && (
        <div className="row" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
          <span className="text-muted">Compliance settings:</span>
          {orgs.map((o) => (
            <Link key={o.id} className="btn" to={`/standards/settings/${o.id}`}>{o.name}</Link>
          ))}
        </div>
      )}

      <div className="side-grid">
        <div className="stack">
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <ViewToggle mode={viewMode} onChange={setViewMode} />
          </div>

          {rows === null && <p>Loading…</p>}
          {rows !== null && rows.length > 0 && filtered.length === 0 && (
            <p className="text-muted">No compliance standards match your search.</p>
          )}
          {rows !== null && filtered.length > 0 && viewMode === "list" && (
            <DirectoryTable
              ariaLabel="Compliance standards"
              columns={columns}
              rows={filtered}
              rowKey={(s) => s.id}
              onRowClick={(s) => navigate(`/standards/${s.id}`)}
              emptyState={<p className="text-muted">No compliance standards yet.</p>}
            />
          )}
          {rows !== null && filtered.length > 0 && viewMode === "tiles" && (
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(min(280px, 100%), 1fr))" }}>
              {filtered.map((s) => (
                <Link
                  key={s.id}
                  to={`/standards/${s.id}`}
                  className="card stack"
                  style={{ gap: "0.5rem", color: "inherit", textDecoration: "none" }}
                >
                  <div style={{ fontWeight: 600, fontSize: "1.05rem" }}>{s.name}</div>
                  <div className="text-muted" style={{ fontSize: "0.85rem" }}>{s.reference}</div>
                  {showOrgColumn && <div className="text-muted" style={{ fontSize: "0.8rem" }}>{s.organization_name}</div>}
                  <div className="text-muted" style={{ fontSize: "0.85rem" }}>
                    Issuing organisation: {s.issuing_organisation ?? "—"}
                  </div>
                  <div className="text-muted" style={{ fontSize: "0.8rem" }}>{s.is_archived ? "Archived" : "Active"}</div>
                </Link>
              ))}
            </div>
          )}
          {rows !== null && rows.length === 0 && <p className="text-muted">No compliance standards yet.</p>}
        </div>

        <FilterPanel
          sectionKey="compliance.standards"
          total={rows?.length ?? 0}
          matching={filtered.length}
          search={search}
          onSearchChange={setSearch}
          searchPlaceholder="Search standards…"
          searchAriaLabel="Search standards"
        >
          <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
        </FilterPanel>
      </div>

      {creating && (
        <StandardFormModal
          orgs={orgs ?? []}
          error={createError}
          onCancel={() => {
            setCreating(false);
            setCreateError(null);
          }}
          onSave={handleCreate}
        />
      )}

      {importing && (
        <StandardImportModal
          orgs={orgs ?? []}
          onCancel={() => setImporting(false)}
          onImported={handleImported}
        />
      )}
    </div>
  );
}
