/**
 * Module: modules/compliance/StandardNavSection
 *
 * The "Standard" left-nav section (Overview/Details, Versions, History), registered through `module.ts`'s `standaloneWorkspaces`
 * (`modules/types.ts`) and rendered by `Layout.tsx` as a sibling of its "Project" section when the path matches
 * `/standards/(?!settings/)([^/]+)` (this module's declared `matchPath`). `Layout.tsx` never imports it. It uses `NavRailLink`
 * (exported from `components/Layout.tsx`) so links match core rail entries. It is a foldable `NavGroup` (`containsActive`: it
 * renders only on a standard's routes), so folding leaves just the current page's entry.
 * The "Versions" entry is an **expandable nav-rail group** (docs/ux-style-guide.md, "Pattern: expandable nav-rail group"): a
 * disclosure toggle (the `ChevronDown`/`ChevronUp` pair of `CollapsibleSection`, whose card chrome does not fit a rail row) lists
 * one link per version, so a person can jump to a version's workspace. The expanded state persists per user with `useUiPreference`
 * (as `nav_rail_collapsed` and `section_collapsed:*`).
 * - Landing on `/standards/:id/versions/:versionId` expands the group through a render-time override (`routeForcesExpand`), not a
 *   write to the persisted preference, so the route and the person's own choice do not overwrite each other.
 *   `autoExpandSuppressed` lets a click collapse the group while a route forces it open and resets on route change.
 * - The "Versions" row matches its exact path (`location.pathname === versionsBase`), so it is not highlighted beside the
 *   version's own row (as in `ComplianceGlobalNavLink.tsx`).
 * - The toggle is not a bordered `.btn` chip: `.nav-link-row` (theme.css) carries the row's hover and active background, so the
 *   whole row highlights as one surface while the link and the toggle stay two focusable controls (a `<div>` wrapping a real
 *   `<Link>` and a real `<button>`, not nested buttons).
 * - Only `entityId` (the standard id) and `railCollapsed` are passed by the render contract, so the component resolves its
 *   `organization_id` through the global `getStandardById`, as `StandardWorkspacePage.tsx` does.
 */
import { ChevronDown, ChevronRight, History, LayoutDashboard, ListChecks, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { NavGroup } from "../../components/NavGroup";
import { NavRailLink } from "../../components/NavRailLink";
import { useUiPreference } from "../../hooks/useUiPreference";
import * as complianceApi from "./api";
import { COMPLIANCE_STANDARD_VERSION_STATUS_LABEL, type ComplianceStandardVersion } from "./types";
import { useResetOnChange } from "../../hooks/useResetOnChange";

export function StandardNavSection({ entityId, railCollapsed }: { entityId: string; railCollapsed: boolean }) {
  const location = useLocation();
  const [orgId, setOrgId] = useState<string | null>(null);
  const [versions, setVersions] = useState<ComplianceStandardVersion[] | null>(null);
  const [expanded, setExpanded] = useUiPreference<boolean>(`section_collapsed:standardVersionsNav:${entityId}`, false);
  const [autoExpandSuppressed, setAutoExpandSuppressed] = useState(false);

  useResetOnChange([entityId], () => setOrgId(null));

  useEffect(() => {
    complianceApi.getStandardById(entityId).then((standard) => setOrgId(standard.organization_id));
  }, [entityId]);

  useEffect(() => {
    if (!orgId) return;
    complianceApi.listStandardVersions(orgId, entityId).then(setVersions);
  }, [orgId, entityId]);

  const versionsBase = `/standards/${entityId}/versions`;
  const canExpand = !railCollapsed && (versions?.length ?? 0) > 0;
  const onVersionsListExact = location.pathname === versionsBase;

  // 29a: force the group open on a version's own route without persisting
  // that to the stored preference (see this file's own header comment).
  useResetOnChange([location.pathname], () => setAutoExpandSuppressed(false));
  const routeForcesExpand = !autoExpandSuppressed && location.pathname.startsWith(`${versionsBase}/`);
  const effectiveExpanded = expanded || routeForcesExpand;

  function toggleExpanded() {
    if (routeForcesExpand) {
      setAutoExpandSuppressed(true);
      if (expanded) setExpanded(false);
    } else {
      setExpanded(!expanded);
    }
  }

  return (
    <>
      <NavGroup groupKey="standard" label="Standard" railCollapsed={railCollapsed} containsActive>
        <NavRailLink to={`/standards/${entityId}`} exact label="Overview" icon={<LayoutDashboard size={16} />} railCollapsed={railCollapsed} />
        {canExpand ? (
          <div className={`nav-link-row${onVersionsListExact ? " active" : ""}`}>
            <Link to={versionsBase} className="nav-link-row-link" aria-label="Versions">
              <ListChecks size={16} /> <span className="nav-label">Versions</span>
            </Link>
            <button
              type="button"
              className="nav-link-row-toggle"
              aria-label={effectiveExpanded ? "Collapse versions" : "Expand versions"}
              aria-expanded={effectiveExpanded}
              onClick={toggleExpanded}
            >
              {effectiveExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
          </div>
        ) : (
          <NavRailLink to={versionsBase} exact label="Versions" icon={<ListChecks size={16} />} railCollapsed={railCollapsed} />
        )}
        {canExpand && effectiveExpanded && versions && (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {versions.map((version) => {
              const to = `${versionsBase}/${version.id}`;
              const active = location.pathname === to;
              return (
                <li key={version.id}>
                  <Link
                    to={to}
                    className={`nav-link${active ? " active" : ""}`}
                    style={{ paddingLeft: "2rem", fontSize: "0.85rem" }}
                  >
                    <span className="nav-label">
                      {version.version_label} ({COMPLIANCE_STANDARD_VERSION_STATUS_LABEL[version.status]})
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
        {/* This standard's own standards_manager/standards_contributor
            working group. */}
        <NavRailLink to={`/standards/${entityId}/members`} label="Members" icon={<Users size={16} />} railCollapsed={railCollapsed} />
        <NavRailLink to={`/standards/${entityId}/history`} label="History" icon={<History size={16} />} railCollapsed={railCollapsed} />
      </NavGroup>
    </>
  );
}
