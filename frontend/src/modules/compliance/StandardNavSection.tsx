/**
 * Module: modules/compliance/StandardNavSection
 *
 * The "Standard" left-nav section (docs/compliance-module-plan.md Phase 18)
 * — Overview/Details, Versions, History — registered via `module.ts`'s
 * `standaloneWorkspaces` (`modules/types.ts`), rendered by `Layout.tsx` as a
 * sibling structural pattern to its own "Project" section whenever the
 * current path matches `/standards/(?!settings/)([^/]+)` (this module's own
 * declared `matchPath`, not a pattern `Layout.tsx` hardcodes). Never
 * imported by `Layout.tsx` directly — only through that declarative
 * registration, the same boundary `orgAdminSections` already enforces for
 * `OrgAdminPage.tsx`.
 *
 * Uses `NavRailLink`, exported from `components/Layout.tsx` for exactly
 * this kind of module-owned reuse, so these links render indistinguishably
 * from every core rail entry (including the project section's own).
 *
 * Phase 23 introduces this app's first **expandable nav-rail group**: the
 * "Versions" entry gains a disclosure toggle (the same `ChevronDown`/
 * `ChevronUp` pair `CollapsibleSection` already uses for the same meaning
 * elsewhere, though not `CollapsibleSection` itself — its card chrome
 * doesn't fit a nav-rail row) that, when expanded, lists one link per
 * version underneath, so a user can jump straight to a specific version's
 * workspace instead of always landing on the version list first. Expanded/
 * collapsed state persists per-user via `useUiPreference`, the same
 * mechanism `nav_rail_collapsed`/`section_collapsed:*` already use.
 * Documented as a reusable pattern in docs/ux-style-guide.md's "Pattern:
 * expandable nav-rail group" for the next project-like drill-down entity
 * with its own many-child collection.
 *
 * Only `entityId` (the standard id) and `railCollapsed` are passed down by
 * `standaloneWorkspaces`' render contract — this component resolves its
 * own `organization_id` via the global, no-org-in-path `getStandardById`
 * the same way `StandardWorkspacePage.tsx` does, rather than that contract
 * growing an org-id field no other workspace needs.
 */
import { ChevronDown, ChevronRight, History, LayoutDashboard, ListChecks, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { NavRailLink } from "../../components/Layout";
import { useUiPreference } from "../../hooks/useUiPreference";
import * as complianceApi from "./api";
import { COMPLIANCE_STANDARD_VERSION_STATUS_LABEL, type ComplianceStandardVersion } from "./types";

export function StandardNavSection({ entityId, railCollapsed }: { entityId: string; railCollapsed: boolean }) {
  const location = useLocation();
  const [orgId, setOrgId] = useState<string | null>(null);
  const [versions, setVersions] = useState<ComplianceStandardVersion[] | null>(null);
  const [expanded, setExpanded] = useUiPreference<boolean>(`section_collapsed:standardVersionsNav:${entityId}`, false);

  useEffect(() => {
    setOrgId(null);
    complianceApi.getStandardById(entityId).then((standard) => setOrgId(standard.organization_id));
  }, [entityId]);

  useEffect(() => {
    if (!orgId) return;
    complianceApi.listStandardVersions(orgId, entityId).then(setVersions);
  }, [orgId, entityId]);

  const versionsBase = `/standards/${entityId}/versions`;
  const canExpand = !railCollapsed && (versions?.length ?? 0) > 0;

  return (
    <>
      <div className="nav-section-label">Standard</div>
      <NavRailLink to={`/standards/${entityId}`} exact label="Overview" icon={<LayoutDashboard size={16} />} railCollapsed={railCollapsed} />
      <div className="row" style={{ alignItems: "stretch", gap: 0 }}>
        <div style={{ flex: 1 }}>
          <NavRailLink to={versionsBase} label="Versions" icon={<ListChecks size={16} />} railCollapsed={railCollapsed} />
        </div>
        {canExpand && (
          <button
            type="button"
            className="btn"
            aria-label={expanded ? "Collapse versions" : "Expand versions"}
            aria-expanded={expanded}
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        )}
      </div>
      {canExpand && expanded && versions && (
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
                    {version.version_label}{" "}
                    <span className="badge">{COMPLIANCE_STANDARD_VERSION_STATUS_LABEL[version.status]}</span>
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
      {/* Phase 22: this standard's own standards_manager/standards_contributor
          working group. */}
      <NavRailLink to={`/standards/${entityId}/members`} label="Members" icon={<Users size={16} />} railCollapsed={railCollapsed} />
      <NavRailLink to={`/standards/${entityId}/history`} label="History" icon={<History size={16} />} railCollapsed={railCollapsed} />
    </>
  );
}
