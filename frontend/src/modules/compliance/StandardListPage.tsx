/**
 * Module: modules/compliance/StandardListPage
 *
 * The cross-org "Compliance Standards" list — the top-level `/standards` tab that promotes standards from
 * three clicks deep inside Org Admin to their own project-like nav entity,
 * modelled directly on `ProjectListPage.tsx`: same `.side-grid` (content
 * column first, `FilterPanel` second — `ProjectListPage.tsx`'s own order,
 * not the backwards order the retired `StandardsPanel.tsx` used), same `showOrgColumn` convention
 * (`orgs.length > 1 || !!user?.is_server_admin`), same Modal-based create
 * flow, same `GET /api/v1/orgs?mine=true` org-fetch pattern.
 *
 * No cross-org backend listing endpoint exists for standards — every
 * compliance route requires `organization_id` in the path (by design). This page gets its rows via `complianceApi.listStandardsAcrossMyOrgs`,
 * the shared org-fan-out-and-collect helper (extracted out of
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
 * row opens `/standards/:standardId`. "Compliance settings" is a row of the page's one actions menu (one row per
 * organisation, grouped when there are several) that opens `/standards/settings/:orgId`
 * (`ComplianceSettingsPage.tsx`).
 *
 * A person in more than one organisation gets an Organisation filter in the filter panel; every organisation they
 * belong to shows until one is chosen (`?org=`), and each standard states its organisation.
 *
 * The page is the first tab of the Standards page: when the person may read compliance status, By standard and
 * Outstanding sit beside it (`StandardsTabs.tsx`).
 *
 * Standard-level import/export: the "New standard"
 * button is a `SplitButtonTrigger`: the default action opens
 * `StandardFormModal`, and an "Import standard" alternative
 * opens `StandardImportModal` — the style guide's "one door" pattern
 * (Principle 5/11), grouping the rarer import path behind the same
 * trigger rather than a second, permanently-visible button competing with
 * "New standard".
 *
 * The `ViewToggle` tile/list split `docs/ux-style-guide.md`'s
 * "Pattern: view toggle" requires of any list page like this one; the tiles
 * are the shared `TileCard` (the title links to the standard), the same card
 * the Projects page draws.
 */
import { Plus } from "lucide-react";
import { Spinner } from "../../components/Spinner";
import { t } from "../../i18n/strings";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import type { Organization } from "../../api/types";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import type { ActionMenuItem } from "../../components/ActionMenu";
import { FilterCheckbox, FilterPanel } from "../../components/FilterPanel";
import { FilterSelect } from "../../components/FilterSelect";
import { ListPageLayout } from "../../components/ListPageLayout";
import { SplitButtonTrigger } from "../../components/SplitButtonTrigger";
import { TileCard, TileGrid } from "../../components/TileCard";
import { useViewMode, ViewToggle } from "../../components/ViewToggle";
import { useAuth } from "../../context/AuthContext";
import { useOrgLabel, useOrgLabelCapitalized, useOrgLabelPlural } from "../../context/BrandingContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import type { StandardAcrossOrgsRow } from "./api";
import { refreshComplianceNavVisibility } from "./useComplianceNavVisibility";
import { StandardFormModal, type EditableStandardFieldValues, type StandardFormValues } from "./StandardFormModal";
import { StandardImportModal } from "./StandardImportModal";
import { useStandardsTabs } from "./StandardsTabs";
import type { StandardImportResult } from "./types";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useUrlChoice, useUrlFlag, useUrlText } from "../../hooks/useUrlFilter";

type StandardListRow = StandardAcrossOrgsRow;

const strings = t().standardsPage;

export function StandardListPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { showToast } = useToast();
  const orgLabel = useOrgLabel();
  const orgLabelCap = useOrgLabelCapitalized();
  const orgLabelPlural = useOrgLabelPlural();

  const [orgs, setOrgs] = useState<Organization[] | null>(null);
  const [rows, setRows] = useState<StandardListRow[] | null>(null);
  // Filters live in the URL so the list comes back as it was left after a visit to a record.
  const [search, setSearch] = useUrlText("q");
  const [includeArchived, setIncludeArchived] = useUrlFlag("archived");
  const [orgChoice, setOrgChoice] = useUrlChoice("org", (orgs ?? []).map((o) => o.id));
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [viewMode, setViewMode] = useViewMode("standards");
  const { tabs, contentProps } = useStandardsTabs("standards");

  async function reload() {
    setRows(null);
    const { orgs: orgList, rows: collected } = await complianceApi.listStandardsAcrossMyOrgs(includeArchived);
    setOrgs(orgList);
    setRows(collected);
  }

  useLoadOnChange(reload, [includeArchived]);

  const showOrgColumn = (orgs?.length ?? 0) > 1 || !!user?.is_server_admin;
  const filtered = (rows ?? []).filter(
    (s) =>
      (!orgChoice || s.organization_id === orgChoice) &&
      (!search || s.name.toLowerCase().includes(search.toLowerCase()) || s.reference.toLowerCase().includes(search.toLowerCase()))
  );
  // One row for a single organisation; with several, one row per organisation under a "Compliance settings" group.
  const settingsItems: ActionMenuItem[] = (orgs ?? []).map((o) => ({
    label: orgs?.length === 1 ? strings.complianceSettings : o.name,
    key: o.id,
    group: orgs?.length === 1 ? undefined : strings.complianceSettings,
    onSelect: () => navigate(`/standards/settings/${o.id}`),
  }));

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
      <ListPageLayout
        title={strings.title}
        tabs={tabs}
        contentProps={contentProps}
        menuItems={settingsItems}
        actions={
          <SplitButtonTrigger
            icon={<Plus size={16} />}
            label="New standard"
            onDefaultAction={() => setCreating(true)}
            menuTitle="New standard"
            moreOptionsLabel="More options"
            disabled={orgs === null}
            alternatives={[{ label: "Import standard", onSelect: () => setImporting(true) }]}
          />
        }
        filter={
          <FilterPanel
            sectionKey="compliance.standards"
            total={rows?.length ?? 0}
            matching={filtered.length}
            search={search}
            onSearchChange={setSearch}
            searchPlaceholder="Search standards…"
            searchAriaLabel="Search standards"
          >
            {orgs !== null && orgs.length > 1 && (
              <FilterSelect
                label={orgLabelCap}
                help={strings.organisationHelpStandards(orgLabel)}
                value={orgChoice}
                onChange={(next: string) => setOrgChoice(next)}
                allLabel={t().projects.allOrganisations(orgLabelPlural)}
                options={orgs.map((o) => ({ value: o.id, label: o.name }))}
              />
            )}
            <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
          </FilterPanel>
        }
      >
          <div className="stack">
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <ViewToggle mode={viewMode} onChange={setViewMode} />
            </div>

            {rows === null && <Spinner />}
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
              <TileGrid>
                {filtered.map((s) => (
                  <TileCard key={s.id} title={s.name} to={`/standards/${s.id}`}>
                    <div className="text-muted" style={{ fontSize: "0.85rem" }}>{s.reference}</div>
                    {showOrgColumn && <div className="text-muted" style={{ fontSize: "0.8rem" }}>{s.organization_name}</div>}
                    <div className="text-muted" style={{ fontSize: "0.85rem" }}>
                      Issuing organisation: {s.issuing_organisation ?? "—"}
                    </div>
                    <div className="text-muted" style={{ fontSize: "0.8rem" }}>{s.is_archived ? "Archived" : "Active"}</div>
                  </TileCard>
                ))}
              </TileGrid>
            )}
            {rows !== null && rows.length === 0 && <p className="text-muted">No compliance standards yet.</p>}
          </div>
      </ListPageLayout>

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
