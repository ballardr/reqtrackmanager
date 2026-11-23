/**
 * Module: modules/compliance/StandardListPage
 *
 * The cross-organisation "Compliance Standards" list, the top-level `/standards` tab, modelled on `ProjectListPage.tsx`: the
 * content column then `FilterPanel`, the `showOrgColumn` convention (`orgs.length > 1 || !!user?.is_server_admin`), a Modal create
 * flow and the `GET /api/v1/orgs?mine=true` fetch. Every compliance route needs `organization_id` in the path, so rows come from
 * `complianceApi.listStandardsAcrossMyOrgs`, the shared fan-out helper (also used by `StandardWorkspacePage.tsx`'s `EntitySwitcher`;
 * see `./api.ts` for its 404-drop and error handling).
 * - "New standard" is a `SplitButtonTrigger`: the default opens `StandardFormModal` (create; an organisation picker first with more
 *   than one candidate) and "Import standard" opens `StandardImportModal`, the "one door" pattern (Principle 5/11).
 * - A row opens `/standards/:standardId`. "Compliance settings" is a row of the page's one actions menu (one per organisation,
 *   grouped when several) that opens `/standards/settings/:orgId`.
 * - A person in more than one organisation gets an Organisation filter; all their organisations show until one is chosen
 *   (`?org=`) and each standard states its organisation.
 * - This is the first tab of the Standards page; By standard and Outstanding sit beside it when the person may read compliance
 *   status (`StandardsTabs.tsx`). A `ViewToggle` splits tiles (the shared `TileCard`, as the Projects page) and list.
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
