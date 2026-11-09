import { useCallback, useEffect, useMemo, useState } from "react";
import { Files, LayoutDashboard, Settings } from "lucide-react";
import { Link, Navigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Organization, OrgDashboard, OrgModule, OrgOverviewStats } from "../api/types";
import { useOrgLabelCapitalized } from "../context/BrandingContext";
import { useStrings } from "../context/TerminologyContext";
import { EntitySwitcher } from "../components/EntitySwitcher";
import { PageActionsProvider, PageActionsSlot } from "../components/PageActions";
import { ReportsButton } from "../components/ReportsButton";
import { ResourceMenu, type ResourceMenuGroupDef } from "../components/ResourceMenu";
import { ManageDashboardsDialog } from "../components/overview/ManageDashboardsDialog";
import { OrgDashboardView } from "../components/overview/OrgDashboardView";
import { Spinner } from "../components/Spinner";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useReportCatalogue } from "../hooks/useReportCatalogue";
import { useReportPackEntries } from "../hooks/useReportPackEntries";
import { installedModules } from "../modules/registry";
import { loadOrgSwitcherOptions } from "../utils/entitySwitcherLoaders";

/** Prefix of the route segment (`/orgs/:orgId/overview/:group`) that names a dashboard page; a module section key never starts with it. */
const DASHBOARD_GROUP_PREFIX = "dashboard-";

/** The `ResourceMenu` group key of a dashboard page: the built-in first page keeps the bare overview address. */
function dashboardGroupKey(page: OrgDashboard): string {
  return page.is_default ? OVERVIEW_GROUP_KEY : `${DASHBOARD_GROUP_PREFIX}${page.id}`;
}

/** The first group: the built-in Overview page, contributed by this core page, so it never collides with a module section key. */
const OVERVIEW_GROUP_KEY = "overview";

/**
 * "Organisation Overview": the always-visible, top-level page of general organisation figures, drawn as widget
 * dashboards. Reached via `/org-overview` (`OrgListPage`'s single-org/multi-org auto-redirect) or directly at
 * `/orgs/:orgId/overview`.
 *
 * The page is a `ResourceMenu` of the dashboard pages the person may see (the built-in Overview first, then any the
 * organisation's administrators added, each optionally limited to chosen people or groups), followed by the sections
 * enabled modules contribute (`orgOverviewSections`, for example Compliance's tables). A dashboard is the same widget grid
 * the project overview uses (`OrgDashboardView`); modules contribute widgets to it through `orgOverviewWidgets`, so this
 * core page never imports a module. An unknown address (a removed section's old link) returns to the Overview.
 *
 * Actions in the title row: a section's own actions (its Export, a dashboard's Customise) are portalled in through
 * `PageActions`, just before Reports, so they stay level with Reports and the group does not shift when switching;
 * "Manage dashboards" (organisation administrators) opens the page list; "Reports" opens the Reports dialog
 * (`ReportsButton`), shown only when the caller can run at least one organisation report or pack; a "files" icon link
 * opens the organisation Files page, shown to every member because it lists only the files of projects the person can
 * open; a "settings" icon link opens the organisation admin page, shown to everyone who can see this page because that
 * page itself loads for every member and gates its sections by role (`docs/decisions.md`).
 */
export function OrgOverviewPage() {
  const { orgId, group: groupParam } = useParams<{ orgId: string; group?: string }>();
  const strings = useStrings();
  const orgLabelCap = useOrgLabelCapitalized();
  const [org, setOrg] = useState<Organization | null>(null);
  const [stats, setStats] = useState<OrgOverviewStats | null>(null);
  const [modules, setModules] = useState<OrgModule[]>([]);
  const [dashboards, setDashboards] = useState<OrgDashboard[] | null>(null);
  const [managing, setManaging] = useState(false);
  const reportCatalogue = useReportCatalogue("organization", orgId);
  const packScope = useMemo(() => (orgId ? { kind: "organization" as const, id: orgId } : undefined), [orgId]);
  const reportPacks = useReportPackEntries(packScope, orgId);

  const loadDashboards = useCallback(async () => {
    if (orgId) setDashboards(await api.get<OrgDashboard[]>(`/api/v1/orgs/${orgId}/dashboards`));
  }, [orgId]);

  useEffect(() => {
    if (!orgId) return;
    api.get<Organization>(`/api/v1/orgs/${orgId}`).then(setOrg);
    api.get<OrgOverviewStats>(`/api/v1/orgs/${orgId}/overview-stats`).then(setStats);
    api.get<OrgModule[]>(`/api/v1/orgs/${orgId}/modules`).then(setModules);
  }, [orgId]);
  useLoadOnChange(loadDashboards, [orgId]);

  if (!orgId) return null;
  if (!org || !stats || !dashboards || reportCatalogue.loading || reportPacks.loading) return <Spinner />;

  // Only the sections of modules this organisation has enabled, as `OrgAdminPage.tsx` does for `orgAdminSections`.
  const enabledModuleKeys = new Set(modules.filter((m) => m.enabled).map((m) => m.module_key));
  const moduleSections = installedModules
    .filter((m) => enabledModuleKeys.has(m.key))
    .flatMap((m) => m.orgOverviewSections ?? []);

  const hasReports = reportCatalogue.entries.length > 0 || reportPacks.entries.length > 0;
  const groups: ResourceMenuGroupDef<string>[] = [
    ...dashboards.map((page) => ({
      key: dashboardGroupKey(page), label: page.name,
      href: page.is_default ? `/orgs/${orgId}/overview` : `/orgs/${orgId}/overview/${dashboardGroupKey(page)}`,
    })),
    ...moduleSections.map((section) => ({
      key: section.key,
      label: section.label,
      href: `/orgs/${orgId}/overview/${section.key}`,
    })),
  ];
  const activeModuleSection = moduleSections.find((s) => s.key === groupParam);
  const activePage = groupParam === undefined
    ? dashboards.find((page) => page.is_default)
    : dashboards.find((page) => dashboardGroupKey(page) === groupParam);
  // An address that names nothing (a removed section, a dashboard the person may not see) returns to the Overview.
  if (groupParam !== undefined && !activeModuleSection && !activePage) return <Navigate to={`/orgs/${orgId}/overview`} replace />;
  const active = activeModuleSection?.key ?? (activePage ? dashboardGroupKey(activePage) : OVERVIEW_GROUP_KEY);
  const canManageDashboards = dashboards.some((page) => page.can_manage);

  return (
    <PageActionsProvider>
    <div className="stack">
      <div className="row" style={{ alignItems: "center", gap: "var(--space-1)" }}>
        <h1 style={{ margin: 0 }}>{org.name}</h1>
        <EntitySwitcher
          label="Switch organisation"
          currentId={orgId}
          loadOptions={() => loadOrgSwitcherOptions("overview")}
        />
        <div className="row" style={{ marginLeft: "auto", alignItems: "center", gap: "var(--space-1)" }}>
          <PageActionsSlot />
          {hasReports && <ReportsButton scope={{ kind: "organization", id: orgId }} organizationId={orgId} />}
          {canManageDashboards && (
            <button
              type="button" className="btn btn-icon" onClick={() => setManaging(true)}
              aria-label={strings.orgDashboards.manage} title={strings.orgDashboards.manage}
            >
              <LayoutDashboard />
            </button>
          )}
          <Link
            to={`/orgs/${orgId}/files`} className="btn btn-icon"
            aria-label={strings.files.orgLink(orgLabelCap)} title={strings.files.orgLink(orgLabelCap)}
          >
            <Files />
          </Link>
          <Link
            to={`/orgs/${orgId}/admin`} className="btn btn-icon"
            aria-label={strings.nav.orgSettings(orgLabelCap)} title={strings.nav.orgSettings(orgLabelCap)}
          >
            <Settings />
          </Link>
        </div>
      </div>

      <ResourceMenu ariaLabel={strings.orgDashboards.menuAria} groups={groups} active={active}>
        {activeModuleSection ? (
          activeModuleSection.render({ orgId })
        ) : (
          <OrgDashboardView
            key={activePage?.id ?? OVERVIEW_GROUP_KEY} orgId={orgId} dashboardId={activePage?.id ?? OVERVIEW_GROUP_KEY}
            scopedFigures={!stats.is_full_org_total}
          />
        )}
      </ResourceMenu>
      {managing && (
        <ManageDashboardsDialog
          organizationId={orgId} pages={dashboards} onClose={() => setManaging(false)} onChanged={() => void loadDashboards()}
        />
      )}
    </div>
    </PageActionsProvider>
  );
}
