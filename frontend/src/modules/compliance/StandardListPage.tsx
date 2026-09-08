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
 * design). This page fetches the caller's orgs, then fans out
 * `complianceApi.listStandards(orgId)` per org in parallel; an org whose
 * call 404s (module disabled there) is dropped silently rather than
 * surfacing an error for it — matching the 404-not-403 "not entitled/
 * disabled looks the same as not present" posture every other compliance
 * endpoint already gives, applied here to a cross-org fan-out instead of a
 * single lookup. A non-404 failure is also dropped (logged, not surfaced)
 * rather than failing the whole page over one org's own hiccup.
 *
 * "New standard" opens the same `StandardFormModal` `StandardWorkspacePage
 * .tsx` uses for editing, in create mode — an org picker (its own first
 * field, shown only when there's more than one candidate) precedes the
 * standard's own fields when the caller has more than one org to create in,
 * mirroring `ProjectListPage.tsx`'s "New project" org picker exactly. Each
 * row opens `/standards/:standardId`. A "Compliance settings" link per org
 * opens `/standards/settings/:orgId` (`ComplianceSettingsPage.tsx`).
 */
import { Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, ApiError } from "../../api/client";
import type { Organization } from "../../api/types";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterPanel } from "../../components/FilterPanel";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import { refreshComplianceNavVisibility } from "./useComplianceNavVisibility";
import { StandardFormModal, type EditableStandardFieldValues, type StandardFormValues } from "./StandardFormModal";
import type { ComplianceStandard } from "./types";

interface StandardListRow extends ComplianceStandard {
  organization_name: string;
}

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

  async function reload() {
    setRows(null);
    const orgList = (await api.get<Organization[]>("/api/v1/orgs?mine=true")).filter((o) => o.is_active);
    setOrgs(orgList);

    const perOrg = await Promise.allSettled(
      orgList.map(async (org) => {
        const standards = await complianceApi.listStandards(org.id, includeArchived);
        return standards.map((s): StandardListRow => ({ ...s, organization_name: org.name }));
      })
    );
    const collected: StandardListRow[] = [];
    for (const result of perOrg) {
      // A rejected org (404 = module disabled there, or any other transient
      // failure) simply contributes no rows — see this file's own docstring
      // for why that's the right default for a best-effort cross-org fan-out.
      if (result.status === "fulfilled") collected.push(...result.value);
      else if (!(result.reason instanceof ApiError) || result.reason.status !== 404) {
        console.error("Could not load compliance standards for one organisation:", result.reason);
      }
    }
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

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>Compliance Standards</h1>
        <button className="btn btn-primary" onClick={() => setCreating(true)}>
          <Plus size={16} /> New standard
        </button>
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
          {rows === null && <p>Loading…</p>}
          {rows !== null && (
            <DirectoryTable
              ariaLabel="Compliance standards"
              columns={columns}
              rows={filtered}
              rowKey={(s) => s.id}
              onRowClick={(s) => navigate(`/standards/${s.id}`)}
              emptyState={<p className="text-muted">No compliance standards yet.</p>}
            />
          )}
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
    </div>
  );
}
