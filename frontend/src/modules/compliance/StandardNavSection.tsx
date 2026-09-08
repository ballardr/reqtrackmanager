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
 */
import { History, LayoutDashboard, ListChecks, Users } from "lucide-react";

import { NavRailLink } from "../../components/Layout";

export function StandardNavSection({ entityId, railCollapsed }: { entityId: string; railCollapsed: boolean }) {
  return (
    <>
      <div className="nav-section-label">Standard</div>
      <NavRailLink to={`/standards/${entityId}`} exact label="Overview" icon={<LayoutDashboard size={16} />} railCollapsed={railCollapsed} />
      <NavRailLink to={`/standards/${entityId}/versions`} label="Versions" icon={<ListChecks size={16} />} railCollapsed={railCollapsed} />
      {/* Phase 22: this standard's own standards_manager/standards_contributor
          working group. */}
      <NavRailLink to={`/standards/${entityId}/members`} label="Members" icon={<Users size={16} />} railCollapsed={railCollapsed} />
      <NavRailLink to={`/standards/${entityId}/history`} label="History" icon={<History size={16} />} railCollapsed={railCollapsed} />
    </>
  );
}
