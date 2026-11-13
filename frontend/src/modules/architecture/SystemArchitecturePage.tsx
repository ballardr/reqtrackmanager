/**
 * Module: modules/architecture/SystemArchitecturePage
 *
 * The one System Architecture page, mounted at `/projects/:projectId/modules/architecture` (the module's single
 * navigation entry). A shared `Tabs` strip switches between the Elements, Connections and Diagrams lists; the
 * chosen tab is the `tab` query parameter and each list keeps its own filters in the same address.
 *
 * - A tab whose sub-component is off for the project is not offered; an address naming one opens the first
 *   enabled tab.
 * - Leaving a tab remembers its filters for the browser session (`sessionStorage`, guarded), and returning to it
 *   restores them, so moving between tabs does not reset a search or a status filter.
 * - `ArchitectureListRedirect` carries the earlier list addresses (`/elements`, `/connections`, `/diagrams`) here.
 */
import { useEffect, useMemo } from "react";
import { Navigate, useLocation, useNavigate, useParams } from "react-router-dom";

import { Tabs, tabPanelProps } from "../../components/Tabs";
import { useProjectEnabledModules } from "../../hooks/useProjectEnabledModules";
import {
  ARCHITECTURE_TABS, architectureTabPath, type ArchitectureListChrome, type ArchitectureTab,
} from "./architectureTabs";
import { ProjectConnectionsPage } from "./ProjectConnectionsPage";
import { ProjectDiagramsPage } from "./ProjectDiagramsPage";
import { ProjectElementsPage } from "./ProjectElementsPage";

const MODULE_KEY = "architecture";
const ID_PREFIX = "architecture-page";
const SAVED_FILTERS_PREFIX = "architecture-tab-filters:";

function savedFiltersKey(projectId: string, tab: ArchitectureTab): string {
  return `${SAVED_FILTERS_PREFIX}${projectId}:${tab}`;
}

/** The filters a tab was last left with, or an empty string; storage that is blocked reads as none. */
function readSavedFilters(projectId: string, tab: ArchitectureTab): string {
  try {
    return sessionStorage.getItem(savedFiltersKey(projectId, tab)) ?? "";
  } catch {
    return "";
  }
}

function writeSavedFilters(projectId: string, tab: ArchitectureTab, filters: string): void {
  try {
    sessionStorage.setItem(savedFiltersKey(projectId, tab), filters);
  } catch {
    // Storage blocked or full: the tab opens with no filters next time.
  }
}

/** A query string without the `tab` parameter: the filters that belong to the tab's list. */
function filtersOf(search: string): string {
  const params = new URLSearchParams(search);
  params.delete("tab");
  return params.toString();
}

/**
 * The System Architecture page: tab strip plus the chosen list.
 *
 * Args: none; the project comes from the route.
 *
 * Returns:
 *   The active list inside its tab panel, or a redirect that makes the tab explicit in the address.
 */
export function SystemArchitecturePage() {
  const { projectId = "" } = useParams<{ projectId: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const { modules } = useProjectEnabledModules(projectId || null);

  const disabled = useMemo(
    () => modules.find((m) => m.module_key === MODULE_KEY)?.disabled_sub_components ?? [],
    [modules],
  );
  const tabs = useMemo(() => ARCHITECTURE_TABS.filter((t) => !disabled.includes(t.subComponent)), [disabled]);

  const requested = new URLSearchParams(location.search).get("tab");
  const active = tabs.find((t) => t.key === requested)?.key ?? tabs[0]?.key ?? "elements";

  // Keep the shown tab's filters current so leaving the tab by any route (a record link, another tab) saves them.
  const filters = filtersOf(location.search);
  useEffect(() => {
    if (projectId && requested === active) writeSavedFilters(projectId, active, filters);
  }, [projectId, requested, active, filters]);

  if (!projectId) return null;
  // The address always names its tab, so the list's saved position and back link are keyed per tab.
  if (requested !== active) {
    const params = new URLSearchParams(location.search);
    params.set("tab", active);
    return <Navigate replace to={`${location.pathname}?${params.toString()}`} />;
  }

  function switchTab(next: ArchitectureTab) {
    const saved = readSavedFilters(projectId, next);
    navigate(saved ? `${architectureTabPath(projectId, next)}&${saved}` : architectureTabPath(projectId, next));
  }

  const chrome: ArchitectureListChrome = {
    tabs: <Tabs idPrefix={ID_PREFIX} tabs={tabs} active={active} onChange={switchTab} />,
    contentProps: tabPanelProps(ID_PREFIX, active),
  };

  if (active === "connections") return <ProjectConnectionsPage chrome={chrome} />;
  if (active === "diagrams") return <ProjectDiagramsPage chrome={chrome} />;
  return <ProjectElementsPage chrome={chrome} />;
}

/**
 * Sends an earlier list address to its tab of the System Architecture page, keeping the filters in its query.
 *
 * Args:
 *   tab: The tab the old address now means.
 *
 * Returns:
 *   A replacing redirect.
 */
export function ArchitectureListRedirect({ tab }: { tab: ArchitectureTab }) {
  const { projectId = "" } = useParams<{ projectId: string }>();
  const { search } = useLocation();
  const params = new URLSearchParams(search);
  params.set("tab", tab);
  return <Navigate replace to={`/projects/${projectId}/modules/architecture?${params.toString()}`} />;
}
