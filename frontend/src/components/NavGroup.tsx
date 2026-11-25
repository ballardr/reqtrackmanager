/**
 * Module: components/NavGroup
 *
 * One labelled group of the navigation rail (Project, Standard, Global, Administration, or one a module
 * contributes) that the person can fold to shorten the rail.
 *
 * - The label is a plain disclosure button (`aria-expanded`, keyboard operable) with a chevron; the entries are
 *   hidden while folded. The folded state is stored per person (`useUiPreference`, key
 *   `nav_group_folded:<groupKey>`). With an icon-only rail there is no chevron and every entry shows.
 * - The current page is never hidden: arriving at a page in a folded group unfolds it, and folding a group that
 *   holds the current page keeps just that entry visible (`.nav-group-body-peek` hides every other `.nav-link` and
 *   `.nav-link-row` in CSS).
 * - The group knows nothing about its entries: `NavRailLink` reports its active state through
 *   `useNavGroupActive`, so core and module entries are found without a per-module case; an entry that is not a
 *   `NavRailLink` passes `containsActive`. Entries stay mounted while folded, so a module entry that decides its
 *   own visibility is still known to the group.
 *
 * Depends on `useUiPreference` (server-stored `ui_preferences`) and `TreeChevron`.
 */
import { useCallback, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";

import { NavGroupContext } from "../hooks/useNavGroupActive";
import { useUiPreference } from "../hooks/useUiPreference";
import { TreeChevron } from "./TreeToggle";

/**
 * A foldable group of navigation entries.
 *
 * @param groupKey Stable key of the group; the stored state is `nav_group_folded:<groupKey>`.
 * @param label The group's heading.
 * @param railCollapsed Whether the rail is icon-only (by preference or narrow viewport).
 * @param containsActive Set when an entry that is not a `NavRailLink` is the current page.
 * @param action An optional control drawn at the right of the heading (the Project group's customise button).
 * @param children The group's entries.
 * @returns The heading and the entries.
 */
export function NavGroup({
  groupKey, label, railCollapsed, containsActive = false, action, children,
}: {
  groupKey: string;
  label: string;
  railCollapsed: boolean;
  containsActive?: boolean;
  action?: ReactNode;
  children: ReactNode;
}) {
  const bodyId = useId();
  const location = useLocation();
  const [folded, setFolded] = useUiPreference<boolean>(`nav_group_folded:${groupKey}`, false);
  const [activeCount, setActiveCount] = useState(0);
  const markActive = useCallback(() => {
    setActiveCount((count) => count + 1);
    return () => setActiveCount((count) => count - 1);
  }, []);
  const context = useMemo(() => ({ markActive }), [markActive]);

  const holdsCurrentPage = containsActive || activeCount > 0;
  // Opening a page inside a folded group unfolds it, once per page: folding the group afterwards (leaving just the
  // current entry) is not undone until the person moves to another page.
  const arrivalKey = holdsCurrentPage ? location.pathname : null;
  const handledArrival = useRef<string | null>(null);
  useEffect(() => {
    if (arrivalKey === null) {
      handledArrival.current = null;
      return;
    }
    if (handledArrival.current === arrivalKey) return;
    handledArrival.current = arrivalKey;
    if (folded) setFolded(false);
  }, [arrivalKey, folded, setFolded]);

  const showFolded = folded && !railCollapsed;
  const bodyClass = `nav-group-body stack${showFolded && holdsCurrentPage ? " nav-group-body-peek" : ""}`;

  return (
    <NavGroupContext.Provider value={context}>
      <div className={`nav-section-label${action ? " nav-section-label-with-action" : ""}`}>
        {railCollapsed ? <span>{label}</span> : (
          <button
            type="button" className="nav-group-toggle" aria-expanded={!showFolded} aria-controls={bodyId}
            onClick={() => setFolded(!folded)}
          >
            <span className="nav-group-chevron"><TreeChevron expanded={!showFolded} /></span>
            <span>{label}</span>
          </button>
        )}
        {!railCollapsed && action}
      </div>
      <div id={bodyId} className={bodyClass} style={{ gap: "0.15rem" }} hidden={showFolded && !holdsCurrentPage}>
        {children}
      </div>
    </NavGroupContext.Provider>
  );
}
