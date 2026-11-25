/**
 * Module: components/DetailLayout
 *
 * The shared frame of an artefact detail page: content in the main column and a persistent aside (the Links panel)
 * beside it ("detail page with links aside" in `docs/ux-style-guide.md`; `SidePanel` is an overlay, not reused).
 *
 * - At 1280px and wider the aside is a sticky right-hand column the user can collapse (`detail_aside_collapsed`,
 *   stored per user, default open); below it the aside stacks under the content with no toggle.
 * - The aside is one card titled by its tab strip (Links, Activity, plus `extraTabs`) or a single "Links" heading;
 *   a panel inside draws no card of its own (`detailAsideContext`). The selected tab is the per-viewer
 *   `detail_aside_tab`; a stored tab the page does not offer falls back to Links. Tabs stay mounted while hidden
 *   except Activity, which loads fresh when opened. Wide tables stay in the body.
 * - Content is drawn in the default card order (`detailCardOrder`); pass cards directly, not in a wrapper. A page
 *   with attachments passes `pictures` so its Markdown fields offer a Picture button.
 * - It renders its own `.container` unless `contained` is false.
 */
import { PanelRightClose, PanelRightOpen } from "lucide-react";
import type { ReactNode } from "react";

import { useNarrowViewport } from "../hooks/useNarrowViewport";
import { useUiPreference } from "../hooks/useUiPreference";
import { useStrings } from "../context/TerminologyContext";
import { DetailAsideProvider } from "./detailAsideContext";
import { orderDetailChildren } from "./detailCardOrder";
import { MarkdownImageSourceProvider } from "./MarkdownImageSource";
import type { MarkdownImageSource } from "./markdownImageSourceContext";
import { Tabs, tabPanelProps } from "./Tabs";

type AsideTab = string;

/** A tab a detail page adds to the aside card after Links and Activity. */
export interface DetailAsideTab {
  /** Stable key, stored as the viewer's chosen tab (`detail_aside_tab`). */
  key: string;
  /** The tab's visible text; it may carry a count. */
  label: string;
  content: ReactNode;
}

const ASIDE_TAB_ID_PREFIX = "detail-aside";

/** Viewport width (px) below which the aside stacks under the content. */
export const DETAIL_ASIDE_BREAKPOINT_PX = 1279;

/**
 * A detail page's content with an optional aside.
 *
 * @param children The page content (rendered in a `.stack` column).
 * @param aside The aside content; omitted or `null` renders the content alone.
 * @param activity The record's activity timeline; when given with `aside`, the aside shows Links and Activity tabs.
 * @param extraTabs Further tabs after Links and Activity; any of them gives the aside a tab strip.
 * @param asideLabel Accessible name for the aside and its toggle (default "Links").
 * @param orderCards Draw the cards in the default order (default). False for a page whose person arranges the sections (the request page), which keeps the order it is given; the page states why.
 * @param contained Wrap in `.container` (default); false for a page already inside a wrapper.
 * @param pictures The record's attachments and upload, for the Picture button of the page's Markdown fields; omitted for a
 *   record with no attachments.
 */
export function DetailLayout({
  children,
  aside,
  activity,
  extraTabs = [],
  asideLabel,
  orderCards = true,
  contained = true,
  pictures,
}: {
  children: ReactNode;
  aside?: ReactNode;
  activity?: ReactNode;
  extraTabs?: DetailAsideTab[];
  asideLabel?: string;
  orderCards?: boolean;
  contained?: boolean;
  pictures?: MarkdownImageSource;
}) {
  const strings = useStrings();
  const narrow = useNarrowViewport(DETAIL_ASIDE_BREAKPOINT_PX);
  const [collapsed, setCollapsed] = useUiPreference<boolean>("detail_aside_collapsed", false);
  const label = asideLabel ?? strings.artefactLinks.title;
  const [storedTab, setStoredTab] = useUiPreference<string>("detail_aside_tab", "links");
  const offered = [...(activity ? ["activity"] : []), ...extraTabs.map((extra) => extra.key)];
  const tab: AsideTab = offered.includes(storedTab) ? storedTab : "links";
  const tabbed = activity || extraTabs.length > 0;
  const ordered = orderCards ? orderDetailChildren(children) : children;
  const content = pictures ? <MarkdownImageSourceProvider files={pictures.files} upload={pictures.upload}>{ordered}</MarkdownImageSourceProvider> : ordered;

  if (aside === undefined || aside === null) {
    return <div className={contained ? "container stack" : "stack"}>{content}</div>;
  }
  const hidden = !narrow && collapsed;
  return (
    <div className={`${contained ? "container " : ""}detail-layout${hidden ? " detail-layout--collapsed" : ""}`}>
      <div className="detail-layout__main stack">{content}</div>
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
            {tabbed ? (
              <>
                <Tabs<AsideTab>
                  idPrefix={ASIDE_TAB_ID_PREFIX}
                  tabs={[
                    { key: "links", label },
                    ...(activity ? [{ key: "activity", label: strings.recordActivity.title }] : []),
                    ...extraTabs.map(({ key, label: extraLabel }) => ({ key, label: extraLabel })),
                  ]}
                  active={tab}
                  onChange={setStoredTab}
                />
                <div {...tabPanelProps(ASIDE_TAB_ID_PREFIX, "links")} hidden={tab !== "links"}>
                  <div className="stack">{aside}</div>
                </div>
                {activity && tab === "activity" && (
                  <div {...tabPanelProps(ASIDE_TAB_ID_PREFIX, "activity")}>{activity}</div>
                )}
                {extraTabs.map((extra) => (
                  <div key={extra.key} {...tabPanelProps(ASIDE_TAB_ID_PREFIX, extra.key)} hidden={tab !== extra.key}>
                    {extra.content}
                  </div>
                ))}
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
