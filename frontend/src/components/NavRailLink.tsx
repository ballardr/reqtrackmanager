import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

import { isNavPathActive } from "../navigation/projectNav";
import { Tooltip } from "./Tooltip";

/**
 * One nav-rail row. The tooltip only wraps the link while the rail is
 * collapsed to icons-only — while expanded, the link already shows its own
 * text label (`nav-label`), so a hover tooltip repeating that same text is
 * pure noise, exactly the complaint that motivated this. `.nav-link` itself
 * is `width: 100%` (see theme.css) so the whole row is clickable/highlit,
 * not just the icon+text's own shrink-wrapped width.
 *
 * Exported (module system follow-up, compliance-module-plan.md Phase 18) so
 * a Tier A module's own `globalNavItems`/`standaloneWorkspaces` render
 * functions (`modules/types.ts`) can build visually-consistent rail links
 * themselves — `Layout.tsx` invites those contributions to render but has
 * no reason to know what any specific one looks like beyond that shared
 * shape, the same "module owns its own UI, core just mounts it" boundary
 * `orgAdminSections` already establishes for `OrgAdminPage.tsx`. Lives in
 * its own file (not `Layout.tsx`) so `ProjectNavSection` can use it without
 * a circular import through `Layout`.
 */
export function NavRailLink({
  to, label, icon, exact = false, railCollapsed, onNavigate,
}: {
  to: string;
  label: string;
  icon: ReactNode;
  exact?: boolean;
  railCollapsed: boolean;
  /** Called when the link is clicked — lets a popover hosting the link close itself. */
  onNavigate?: () => void;
}) {
  const location = useLocation();
  const active = isNavPathActive(location.pathname, to, exact);
  const link = (
    <Link to={to} className={`nav-link${active ? " active" : ""}`} aria-label={label} onClick={onNavigate}>
      {icon} <span className="nav-label">{label}</span>
    </Link>
  );
  return railCollapsed ? <Tooltip label={label}>{link}</Tooltip> : link;
}
