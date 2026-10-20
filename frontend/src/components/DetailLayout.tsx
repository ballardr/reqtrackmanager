/**
 * Module: components/DetailLayout
 *
 * The shared frame of an artefact detail page: the page content in the main
 * column and, beside it, a persistent aside (today the Links panel). Pattern
 * "detail page with links aside" in `docs/ux-style-guide.md`; `SidePanel` is an
 * overlay for row detail and is deliberately not reused for this.
 *
 * - At 1280px and wider the aside is a sticky right-hand column that the user can
 *   collapse; the choice is stored per user (`detail_aside_collapsed`), so it
 *   follows them across pages and devices. Default is open.
 * - Below 1280px the aside stacks under the content, always shown, with no toggle
 *   (a collapse there would only hide what the user scrolled to find).
 * - The aside is one card. Its title is its tab strip (Links, Activity) or, for a page with no
 *   activity, a single "Links" heading; a panel inside it draws no card or title of its own
 *   (`detailAsideContext`), so the word "Links" appears once, wide or stacked.
 * - A page that passes `activity` as well gets two tabs in the aside, Links and Activity; the
 *   selected tab is a per-viewer preference (`detail_aside_tab`). The Links panel stays mounted
 *   while hidden (its state survives a tab switch); the Activity tab mounts when opened, so it
 *   loads fresh each time. Wide tables never go in the aside: a page keeps those in its body.
 *
 * Renders its own `.container` (unless `contained` is false, for a page that already
 * sits in a content wrapper), so a page replaces its root `<div className="container
 * stack">` with this component.
 */
import { PanelRightClose, PanelRightOpen } from "lucide-react";
import type { ReactNode } from "react";

import { useNarrowViewport } from "../hooks/useNarrowViewport";
import { useUiPreference } from "../hooks/useUiPreference";
import { useStrings } from "../context/TerminologyContext";
import { DetailAsideProvider } from "./detailAsideContext";
import { Tabs, tabPanelProps } from "./Tabs";

type AsideTab = "links" | "activity";
const ASIDE_TAB_ID_PREFIX = "detail-aside";

/** Viewport width (px) below which the aside stacks under the content. */
export const DETAIL_ASIDE_BREAKPOINT_PX = 1279;

/**
 * A detail page's content with an optional aside.
 *
 * @param children The page content (rendered in a `.stack` column).
 * @param aside The aside content; omitted or `null` renders the content alone.
 * @param activity The record's activity timeline; when given with `aside`, the aside shows Links and Activity tabs.
 * @param asideLabel Accessible name for the aside and its toggle (default "Links").
 * @param contained Wrap in `.container` (default); false for a page already inside a wrapper.
 */
export function DetailLayout({
  children,
  aside,
  activity,
  asideLabel,
  contained = true,
}: {
  children: ReactNode;
  aside?: ReactNode;
  activity?: ReactNode;
  asideLabel?: string;
  contained?: boolean;
}) {
  const strings = useStrings();
  const narrow = useNarrowViewport(DETAIL_ASIDE_BREAKPOINT_PX);
  const [collapsed, setCollapsed] = useUiPreference<boolean>("detail_aside_collapsed", false);
  const label = asideLabel ?? strings.artefactLinks.title;
  const [storedTab, setStoredTab] = useUiPreference<string>("detail_aside_tab", "links");
  const tab: AsideTab = activity && storedTab === "activity" ? "activity" : "links";

  if (aside === undefined || aside === null) {
    return <div className={contained ? "container stack" : "stack"}>{children}</div>;
  }
  const hidden = !narrow && collapsed;
  return (
    <div className={`${contained ? "container " : ""}detail-layout${hidden ? " detail-layout--collapsed" : ""}`}>
      <div className="detail-layout__main stack">{children}</div>
      <aside className="detail-layout__aside" aria-label={label}>
        {!narrow && (
          <button
            type="button"
            className="btn detail-layout__toggle"
            aria-expanded={!collapsed}
            aria-label={collapsed ? strings.artefactLinks.asideToggleShow : strings.artefactLinks.asideToggleHide}
            title={collapsed ? strings.artefactLinks.asideToggleShow : strings.artefactLinks.asideToggleHide}
            onClick={() => setCollapsed(!collapsed)}
          >
            {collapsed ? <PanelRightOpen /> : <PanelRightClose />}
            {collapsed && <span>{label}</span>}
          </button>
        )}
        {!hidden && (
          <div className="card stack detail-layout__aside-body">
            <DetailAsideProvider value>
            {activity ? (
              <>
                <Tabs<AsideTab>
                  idPrefix={ASIDE_TAB_ID_PREFIX}
                  tabs={[
                    { key: "links", label },
                    { key: "activity", label: strings.recordActivity.title },
                  ]}
                  active={tab}
                  onChange={setStoredTab}
                />
                <div {...tabPanelProps(ASIDE_TAB_ID_PREFIX, "links")} hidden={tab !== "links"}>
                  <div className="stack">{aside}</div>
                </div>
                {tab === "activity" && (
                  <div {...tabPanelProps(ASIDE_TAB_ID_PREFIX, "activity")}>{activity}</div>
                )}
              </>
            ) : (
              <>
                <h2 className="detail-layout__aside-title">{label}</h2>
                {aside}
              </>
            )}
            </DetailAsideProvider>
          </div>
        )}
      </aside>
    </div>
  );
}
