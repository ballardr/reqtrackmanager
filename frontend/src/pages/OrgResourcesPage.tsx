/**
 * Module: pages/OrgResourcesPage
 *
 * "Org Resources" (`/orgs/:orgId/resources/:group?/:section?`): the records and content an organisation owns and shares with its projects,
 * as a `ResourceMenu`. Menu: the enabled modules' `orgResourceSections` (`collectOrgResourceSections`), then the core Reports and Tags sections.
 * Address: `resolveAdminSection` (groups, bare group redirect, unknown address returns to the page; redirects keep query string and hash).
 * Title row: organisation name, switcher, `PageActions`, a link to Organisation Settings.
 * Design: each section's endpoints enforce access; core never imports a module (only `CORE_ORG_RESOURCE_GROUP_KEYS` are named).
 * Dependencies: `GET /orgs/{id}` and `GET /orgs/{id}/enabled-modules` (readable by every member).
 */
import { useState } from "react";
import { Settings } from "lucide-react";
import { Link, Navigate, useLocation, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { OrgEnabledModule, Organization } from "../api/types";
import { EntitySwitcher } from "../components/EntitySwitcher";
import { PageActionsProvider, PageActionsSlot } from "../components/PageActions";
import { ResourceMenu } from "../components/ResourceMenu";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { OrgReportsResources } from "../components/OrgReportsResources";
import { OrgTagsPanel } from "../components/OrgTagsPanel";
import { Spinner } from "../components/Spinner";
import { useOrgLabelCapitalized } from "../context/BrandingContext";
import { useStrings } from "../context/TerminologyContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { buildAdminMenuEntries, resolveAdminSection } from "../modules/adminMenu";
import { collectOrgResourceSections, orgResourcesPath } from "../modules/orgResources";
import type { OrgAdminSectionDef } from "../modules/types";
import { installedModules } from "../modules/registry";
import { loadOrgSwitcherOptions } from "../utils/entitySwitcherLoaders";

/**
 * The Org Resources page for the organisation named in the address.
 *
 * Returns:
 *   The page, a spinner while the organisation and its module state load, or a redirect for a partial or unknown
 *   address.
 */
export function OrgResourcesPage() {
  const { orgId, group, section } = useParams<{ orgId: string; group?: string; section?: string }>();
  const location = useLocation();
  const strings = useStrings();
  const orgLabelCap = useOrgLabelCapitalized();
  const [org, setOrg] = useState<Organization | null>(null);
  const [enabledModules, setEnabledModules] = useState<OrgEnabledModule[] | null>(null);

  useLoadOnChange(async () => {
    if (!orgId) return;
    // The member-readable list: this page is for everyone in the organisation, and `/modules` is for administrators.
    const [loadedOrg, loadedModules] = await Promise.all([
      api.get<Organization>(`/api/v1/orgs/${orgId}`),
      api.get<OrgEnabledModule[]>(`/api/v1/orgs/${orgId}/enabled-modules`),
    ]);
    setOrg(loadedOrg);
    setEnabledModules(loadedModules);
  }, [orgId]);

  if (!orgId) return null;
  if (!org || !enabledModules) return <Spinner />;

  const enabledKeys = new Set(enabledModules.map((m) => m.module_key));
  const disabledSubComponents = Object.fromEntries(enabledModules.map((m) => [m.module_key, m.disabled_sub_components]));
  // Core's own sections follow the modules'; their keys are reserved (`CORE_ORG_RESOURCE_GROUP_KEYS`).
  const coreSections: OrgAdminSectionDef[] = [
    {
      key: "reports", label: strings.orgAdmin.groupReports,
      render: ({ orgId: id }) => <OrgReportsResources orgId={id} />,
    },
    {
      key: "tags", label: strings.orgAdmin.groupTags,
      render: ({ orgId: id }) => (
        <CollapsibleSection sectionKey="orgAdmin.tags" collapsible={false} title={strings.tags.admin.title}>
          <OrgTagsPanel organizationId={id} />
        </CollapsibleSection>
      ),
    },
  ];
  const sections = [...collectOrgResourceSections(installedModules, enabledKeys, disabledSubComponents), ...coreSections];
  const base = orgResourcesPath(orgId);
  const route = resolveAdminSection(sections, base, group, section);
  if (route.redirectTo) return <Navigate to={`${route.redirectTo}${location.search}${location.hash}`} replace />;
  // An address that names nothing (a section of a module since switched off, a mistyped key) returns to the page.
  if (group !== undefined && !route.section) return <Navigate to={base} replace />;
  // Core always contributes sections, so the first entry is the landing section.
  const active = route.section ?? sections[0];

  return (
    <PageActionsProvider>
      <div className="stack">
        <div className="row" style={{ alignItems: "center", gap: "var(--space-1)" }}>
          <h1 style={{ margin: 0 }}>{org.name}</h1>
          <EntitySwitcher
            label="Switch organisation"
            currentId={orgId}
            loadOptions={() => loadOrgSwitcherOptions("resources")}
          />
          <div className="row" style={{ marginLeft: "auto", alignItems: "center", gap: "var(--space-1)" }}>
            <PageActionsSlot />
            <Link
              to={`/orgs/${orgId}/admin`} className="btn btn-icon"
              aria-label={strings.nav.orgSettings(orgLabelCap)} title={strings.nav.orgSettings(orgLabelCap)}
            >
              <Settings />
            </Link>
          </div>
        </div>

        <ResourceMenu ariaLabel={strings.orgResources.menuAria} groups={buildAdminMenuEntries(sections, base)} active={active.key}>
          {/* Keyed by section so one section's state never carries into the next. */}
          <div key={active.key}>{active.render({ orgId })}</div>
        </ResourceMenu>
      </div>
    </PageActionsProvider>
  );
}
