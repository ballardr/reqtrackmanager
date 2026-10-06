/**
 * Module: components/ProjectNavSection
 *
 * The "Project" section of the nav rail (docs/plans/platform-enhancements-2026-10-plan.md
 * Phase 4): the project's nav items in the user's chosen order, a "More" disclosure for the
 * ones they moved out of the way, and the entry point to the layout editor.
 *
 * Responsibilities:
 * - Resolve the layout in effect (per-project override, else the user's default, else the
 *   product default) and arrange the items it is given (`navigation/projectNav`).
 * - Render "More" as an inline disclosure in the expanded rail and as a `Popover` in the
 *   icon-only rail, where there is no room to expand inline.
 * - Offer "Customise navigation" from the section label (expanded) or its own rail row
 *   (icon-only, where the label is collapsed to a divider).
 *
 * Design decisions:
 * - Knows nothing about which items exist: `Layout` passes core and module items alike as
 *   generic `ProjectNavItem`s, so no module is named here (module-boundary rule).
 * - The active route's item is never hidden behind More (`layoutProjectNav`).
 */
import { ChevronDown, ChevronRight, MoreHorizontal, SlidersHorizontal } from "lucide-react";
import { useId, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

import { useAuth } from "../context/AuthContext";
import { useStrings } from "../context/TerminologyContext";
import {
  layoutProjectNav,
  PROJECT_NAV_PREF_KEY,
  projectNavOverrideKey,
  resolveNavPref,
  type ProjectNavItem,
} from "../navigation/projectNav";
import { NavRailLink } from "./NavRailLink";
import { Popover } from "./Popover";
import { ProjectNavEditor } from "./ProjectNavEditor";
import { Tooltip } from "./Tooltip";

/**
 * Renders the Project nav section's label and links.
 *
 * Args:
 *   projectId: The current project; scopes the per-project override.
 *   items: Every available item in product-default order.
 *   railCollapsed: Whether the rail is currently icon-only (by preference or narrow viewport).
 */
export function ProjectNavSection({
  projectId, items, railCollapsed,
}: { projectId: string; items: ProjectNavItem[]; railCollapsed: boolean }) {
  const strings = useStrings();
  const location = useLocation();
  const { user } = useAuth();
  const [moreOpen, setMoreOpen] = useState(false);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const moreTriggerRef = useRef<HTMLButtonElement>(null);
  const moreListId = useId();

  const prefs = user?.ui_preferences ?? {};
  const pref = resolveNavPref(prefs[PROJECT_NAV_PREF_KEY], prefs[projectNavOverrideKey(projectId)]);
  const { main, more } = layoutProjectNav(items, pref, location.pathname);
  const customiseLabel = strings.nav.customise.title;

  function renderLink(item: ProjectNavItem, collapsed: boolean, onNavigate?: () => void) {
    return (
      <NavRailLink
        key={item.key} to={item.to} exact={item.exact} label={item.label} icon={item.icon}
        railCollapsed={collapsed} onNavigate={onNavigate}
      />
    );
  }

  return (
    <>
      <div className="nav-section-label nav-section-label-with-action">
        <span>{strings.nav.projectSectionLabel}</span>
        {!railCollapsed && (
          <button
            type="button" className="nav-section-action" aria-label={customiseLabel} title={customiseLabel}
            onClick={() => setEditorOpen(true)}
          >
            <SlidersHorizontal size={12} />
          </button>
        )}
      </div>
      {main.map((item) => renderLink(item, railCollapsed))}
      {more.length > 0 && !railCollapsed && (
        <>
          <button
            type="button" className="nav-link nav-link-button" aria-expanded={moreOpen} aria-controls={moreListId}
            onClick={() => setMoreOpen(!moreOpen)}
          >
            <MoreHorizontal size={16} /> <span className="nav-label">{strings.nav.more}</span>
            <span className="nav-link-button-chevron">{moreOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</span>
          </button>
          {moreOpen && (
            <div id={moreListId} className="nav-more-list">
              {more.map((item) => renderLink(item, false))}
            </div>
          )}
        </>
      )}
      {more.length > 0 && railCollapsed && (
        <>
          <Tooltip label={strings.nav.more}>
            <button
              ref={moreTriggerRef} type="button" className="nav-link nav-link-button" aria-label={strings.nav.more}
              aria-haspopup="dialog" aria-expanded={popoverOpen} onClick={() => setPopoverOpen(!popoverOpen)}
            >
              <MoreHorizontal size={16} />
            </button>
          </Tooltip>
          {popoverOpen && (
            <Popover anchorRef={moreTriggerRef} title={strings.nav.more} onClose={() => setPopoverOpen(false)}>
              <div className="stack" style={{ gap: "0.15rem" }}>
                {more.map((item) => renderLink(item, false, () => setPopoverOpen(false)))}
              </div>
            </Popover>
          )}
        </>
      )}
      {railCollapsed && (
        <Tooltip label={customiseLabel}>
          <button type="button" className="nav-link nav-link-button" aria-label={customiseLabel} onClick={() => setEditorOpen(true)}>
            <SlidersHorizontal size={16} />
          </button>
        </Tooltip>
      )}
      {editorOpen && <ProjectNavEditor projectId={projectId} items={items} onClose={() => setEditorOpen(false)} />}
    </>
  );
}
