/**
 * Module: pages/OrgResourcesPage
 *
 * "Org Resources" (`/orgs/:orgId/resources/:group?/:section?`): the records and content an organisation owns and
 * shares with its projects, as a `ResourceMenu` of sections. Organisation Settings holds configuration and the
 * Organisation Overview holds computed figures; this page holds what people open to work in.
 *
 * Responsibilities:
 * - Build the menu from `orgResourceSections` of the installed modules enabled for the organisation
 *   (`collectOrgResourceSections`), so a disabled module, or a sub-component that is off, is not offered.
 * - Resolve the address with the shared admin-menu rules (`resolveAdminSection`): grouped sections, a bare group
 *   redirecting to its first section, an unknown address returning to the page. Redirects keep the query string and
 *   hash, because a section's own filters live in the URL.
 * - Provide the title row (organisation name, switcher, a section's own actions through `PageActions`, a link to
 *   Organisation Settings).
 *
 * Design decisions: the page decides nothing about access. Each section's endpoints enforce their permission, so a
 * section a person may not use shows the error its endpoint returns. Core never imports a module: sections arrive
 * through the registry only. With no enabled module contributing, the page is an explained empty state, not an error.
 *
 * Dependencies: `GET /orgs/{id}`, `GET /orgs/{id}/modules` and, only for modules whose sections declare a
 * sub-component, `GET /orgs/{id}/modules/{key}/subcomponents` (readable by administrators; where the caller cannot read
 * it the sub-component filter does not apply).
 */
import { useState } from "react";
import { Settings } from "lucide-react";
import { Link, Navigate, useLocation, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Organization, OrgModule, OrgModuleSubComponent } from "../api/types";
import { EntitySwitcher } from "../components/EntitySwitcher";
import { PageActionsProvider, PageActionsSlot } from "../components/PageActions";
import { ResourceMenu } from "../components/ResourceMenu";
import { Spinner } from "../components/Spinner";
import { useOrgLabelCapitalized } from "../context/BrandingContext";
import { useStrings } from "../context/TerminologyContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { buildAdminMenuEntries, resolveAdminSection } from "../modules/adminMenu";
import { collectOrgResourceSections, orgResourcesPath } from "../modules/orgResources";
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
  const [modules, setModules] = useState<OrgModule[] | null>(null);
  const [subComponents, setSubComponents] = useState<Record<string, OrgModuleSubComponent[] | undefined>>({});

  useLoadOnChange(async () => {
    if (!orgId) return;
    const [loadedOrg, loadedModules] = await Promise.all([
      api.get<Organization>(`/api/v1/orgs/${orgId}`),
      api.get<OrgModule[]>(`/api/v1/orgs/${orgId}/modules`),
    ]);
    // Only a module with a sub-component-tied section needs the state; a caller who cannot read it is not filtered.
    const asked = installedModules.filter(
      (m) => loadedModules.some((om) => om.module_key === m.key && om.enabled) &&
        (m.orgResourceSections ?? []).some((s) => s.subComponent),
    );
    const entries = await Promise.all(
      asked.map(async (m) => {
        try {
          return [m.key, await api.get<OrgModuleSubComponent[]>(`/api/v1/orgs/${orgId}/modules/${m.key}/subcomponents`)] as const;
        } catch {
          return [m.key, undefined] as const;
        }
      }),
    );
    setSubComponents(Object.fromEntries(entries));
    setOrg(loadedOrg);
    setModules(loadedModules);
  }, [orgId]);

  if (!orgId) return null;
  if (!org || !modules) return <Spinner />;

  const enabledKeys = new Set(modules.filter((m) => m.enabled).map((m) => m.module_key));
  const sections = collectOrgResourceSections(installedModules, enabledKeys, subComponents);
  const base = orgResourcesPath(orgId);
  const route = resolveAdminSection(sections, base, group, section);
  if (route.redirectTo) return <Navigate to={`${route.redirectTo}${location.search}${location.hash}`} replace />;
  // An address that names nothing (a section of a module since switched off, a mistyped key) returns to the page.
  if (group !== undefined && !route.section) return <Navigate to={base} replace />;
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

        {active ? (
          <ResourceMenu ariaLabel={strings.orgResources.menuAria} groups={buildAdminMenuEntries(sections, base)} active={active.key}>
            {/* Keyed by section so one section's state never carries into the next. */}
            <div key={active.key}>{active.render({ orgId })}</div>
          </ResourceMenu>
        ) : (
          <p className="text-muted">{strings.orgResources.empty}</p>
        )}
      </div>
    </PageActionsProvider>
  );
}
