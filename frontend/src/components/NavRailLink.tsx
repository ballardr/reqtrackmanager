import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

import { useNavGroupActive } from "../hooks/useNavGroupActive";
import { isNavPathActive } from "../navigation/projectNav";
import { Tooltip } from "./Tooltip";

/**
 * One nav-rail row. The tooltip wraps the link only while the rail is collapsed to icons, because an expanded link
 * already shows its text label (`nav-label`). `.nav-link` is `width: 100%` (theme.css) so the whole row is
 * clickable and highlighted.
 *
 * Exported so a Tier A module's `globalNavItems`/`standaloneWorkspaces` render functions (`modules/types.ts`) can
 * build visually consistent rail links: the module owns its UI and core only mounts it, as `orgAdminSections` does
 * for `OrgAdminPage.tsx`. It lives in its own file so `ProjectNavSection` can use it without a circular import
 * through `Layout`.
 */
export function NavRailLink({
  to, label, icon, exact = false, alsoActiveOn, railCollapsed, onNavigate,
}: {
  to: string;
  label: string;
  icon: ReactNode;
  exact?: boolean;
  /** Another route family that also marks this entry active (an entry that redirects to a per-record page). */
  alsoActiveOn?: RegExp;
  railCollapsed: boolean;
  /** Called when the link is clicked — lets a popover hosting the link close itself. */
  onNavigate?: () => void;
}) {
  const location = useLocation();
  const active = isNavPathActive(location.pathname, to, exact) || (alsoActiveOn?.test(location.pathname) ?? false);
  useNavGroupActive(active);
  const link = (
    <Link to={to} className={`nav-link${active ? " active" : ""}`} aria-label={label} onClick={onNavigate}>
      {icon} <span className="nav-label">{label}</span>
    </Link>
  );
  return railCollapsed ? <Tooltip label={label}>{link}</Tooltip> : link;
}
