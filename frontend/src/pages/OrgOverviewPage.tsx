import { useCallback, useEffect, useMemo, useState } from "react";
import { Files, LayoutDashboard, Settings } from "lucide-react";
import { Link, Navigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Organization, OrgDashboard, OrgOverviewStats } from "../api/types";
import { useOrgLabelCapitalized } from "../context/BrandingContext";
import { useStrings } from "../context/TerminologyContext";
import { EntitySwitcher } from "../components/EntitySwitcher";
import { LoadFailed } from "../components/LoadFailed";
import { PageActionsProvider, PageActionsSlot } from "../components/PageActions";
import { ReportsButton } from "../components/ReportsButton";
import { ResourceMenu, type ResourceMenuGroupDef } from "../components/ResourceMenu";
import { ManageDashboardsDialog } from "../components/overview/ManageDashboardsDialog";
import { OrgDashboardView } from "../components/overview/OrgDashboardView";
import { Spinner } from "../components/Spinner";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useReportCatalogue } from "../hooks/useReportCatalogue";
import { useReportPackEntries } from "../hooks/useReportPackEntries";
import { loadOrgSwitcherOptions } from "../utils/entitySwitcherLoaders";

/** Prefix of the route segment (`/orgs/:orgId/overview/:group`) that names a dashboard page; a section key never starts with it. */
const DASHBOARD_GROUP_PREFIX = "dashboard-";

/** The `ResourceMenu` group key of a dashboard page: the built-in first page keeps the bare overview address. */
function dashboardGroupKey(page: OrgDashboard): string {
  return page.is_default ? OVERVIEW_GROUP_KEY : `${DASHBOARD_GROUP_PREFIX}${page.id}`;
}

/** The first group: the built-in Overview page, contributed by this core page, so it never collides with a module section key. */
const OVERVIEW_GROUP_KEY = "overview";

/**
 * "Organisation Overview": the top-level page of organisation figures as widget dashboards, reached via `/org-overview` (`OrgListPage`) or
 * `/orgs/:orgId/overview`. A `ResourceMenu` of the dashboard pages the person may see (the built-in Overview first, then administrator-added
 * ones, optionally limited to people or groups); a dashboard is the project overview's widget grid (`OrgDashboardView`) and modules add widgets
 * through `orgOverviewWidgets`, so no module is imported. An unknown address returns to the Overview.
 *
 * Title row: a section's own actions (Export, Customise) are portalled in through `PageActions` before Reports so the group does not shift;
 * "Manage dashboards" (administrators); "Reports" (`ReportsButton`, only when the caller can run an organisation report or pack); a files icon
 * link (every member; only files of projects they can open); a settings icon link (every viewer; that page gates its sections by role).
 */
export function OrgOverviewPage() {
  const { orgId, group: groupParam } = useParams<{ orgId: string; group?: string }>();
  const strings = useStrings();
  const orgLabelCap = useOrgLabelCapitalized();
  const [org, setOrg] = useState<Organization | null>(null);
  const [stats, setStats] = useState<OrgOverviewStats | null>(null);
  const [dashboards, setDashboards] = useState<OrgDashboard[] | null>(null);
  const [managing, setManaging] = useState(false);
  // A refused read shows the failure with Retry (`attempt` loads the same organisation again).
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const reportCatalogue = useReportCatalogue("organization", orgId);
  const packScope = useMemo(() => (orgId ? { kind: "organization" as const, id: orgId } : undefined), [orgId]);
  const reportPacks = useReportPackEntries(packScope, orgId);

  const loadDashboards = useCallback(async () => {
    if (orgId) setDashboards(await api.get<OrgDashboard[]>(`/api/v1/orgs/${orgId}/dashboards`));
  }, [orgId]);

  useEffect(() => {
    if (!orgId) return;
    const refused = () => setFailed(true);
    api.get<Organization>(`/api/v1/orgs/${orgId}`).then(setOrg, refused);
    api.get<OrgOverviewStats>(`/api/v1/orgs/${orgId}/overview-stats`).then(setStats, refused);
  }, [orgId, attempt]);
  useLoadOnChange(() => loadDashboards().catch(() => setFailed(true)), [orgId, attempt]);

  if (!orgId) return null;
  if (failed) {
    return (
      <LoadFailed
        message={strings.requestFailure.loadFailed(strings.requestFailure.organisationOverview)}
        onRetry={() => {
          setFailed(false);
          setAttempt((n) => n + 1);
        }}
      />
    );
  }
  if (!org || !stats || !dashboards || reportCatalogue.loading || reportPacks.loading) return <Spinner />;

  const hasReports = reportCatalogue.entries.length > 0 || reportPacks.entries.length > 0;
  const groups: ResourceMenuGroupDef<string>[] = dashboards.map((page) => ({
    key: dashboardGroupKey(page), label: page.name,
    href: page.is_default ? `/orgs/${orgId}/overview` : `/orgs/${orgId}/overview/${dashboardGroupKey(page)}`,
  }));
  const activePage = groupParam === undefined
    ? dashboards.find((page) => page.is_default)
    : dashboards.find((page) => dashboardGroupKey(page) === groupParam);
  // An address that names nothing (a removed page, a dashboard the person may not see) returns to the Overview.
  if (groupParam !== undefined && !activePage) return <Navigate to={`/orgs/${orgId}/overview`} replace />;
  const active = activePage ? dashboardGroupKey(activePage) : OVERVIEW_GROUP_KEY;
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
        <OrgDashboardView
          key={activePage?.id ?? OVERVIEW_GROUP_KEY} orgId={orgId} dashboardId={activePage?.id ?? OVERVIEW_GROUP_KEY}
          scopedFigures={!stats.is_full_org_total}
        />
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
