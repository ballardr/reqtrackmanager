/**
 * Module: components/DesignerSidePanel
 *
 * The report designer's right-hand panel: one tab strip over the tools of the view being edited (Block, Preview, Fields,
 * Widgets), that collapses to a rail with an expand button like a record list's filter panel and the detail page's
 * aside (`DetailLayout`).
 *
 * Responsibilities:
 * - Draw the tab strip (`Tabs`) and the collapse/expand button; hold no tab or collapsed state itself (the designer
 *   remembers both per person with `useUiPreference`, as `DetailLayout` does).
 * - Keep the tab panels mounted while another tab or the collapsed rail is showing: the caller renders each panel with
 *   `tabPanelProps(idPrefix, key)` and `hidden`, so a preview result and the block editor's form survive a switch.
 * - Below the designer's stacking breakpoint the panel sits under the editor as a full-width card with no collapse
 *   button (hiding what the author scrolled down to find would only hide it).
 *
 * Design decisions: the collapse toggle, its icons and its `aria-expanded` reading are `DetailLayout`'s, so the two
 * collapsible asides behave alike. The collapsed rail is the button alone; the body is hidden, not unmounted.
 * Depends on `Tabs`, `useNarrowViewport` and the designer's grid classes in `theme.css`.
 */
import { PanelRightClose, PanelRightOpen } from "lucide-react";
import type { ReactNode } from "react";

import { useStrings } from "../context/TerminologyContext";
import { useNarrowViewport } from "../hooks/useNarrowViewport";
import { Tabs, type TabDef } from "./Tabs";

/** Viewport width (px) at or below which the designer's columns stack and the panel sits under the editor. */
export const DESIGNER_STACK_BREAKPOINT_PX = 1099;

/**
 * @param label Accessible name of the panel and its toggle (the region's name).
 * @param idPrefix Prefix shared with each panel's `tabPanelProps`.
 * @param tabs The tabs, in order.
 * @param active The selected tab.
 * @param onChange Called with the tab a person chose.
 * @param collapsed Whether the panel is folded to its rail (ignored when the columns stack).
 * @param onCollapsedChange Called with the new collapsed state.
 * @param children The tab panels, each wrapped in `tabPanelProps(idPrefix, key)` and `hidden` unless active.
 */
export function DesignerSidePanel<K extends string>({
  label, idPrefix, tabs, active, onChange, collapsed, onCollapsedChange, children,
}: {
  label: string;
  idPrefix: string;
  tabs: TabDef<K>[];
  active: K;
  onChange: (key: K) => void;
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  children: ReactNode;
}) {
  const strings = useStrings().reportLayouts;
  const stacked = useNarrowViewport(DESIGNER_STACK_BREAKPOINT_PX);
  const folded = !stacked && collapsed;
  const toggleLabel = folded ? strings.showPanel : strings.hidePanel;
  return (
    <aside className="designer-panel" aria-label={label}>
      {!stacked && (
        <button
          type="button" className="btn designer-panel__toggle" aria-expanded={!folded} aria-label={toggleLabel} title={toggleLabel}
          onClick={() => onCollapsedChange(!collapsed)}
        >
          {folded ? <PanelRightOpen /> : <PanelRightClose />}
        </button>
      )}
      <div className="card stack designer-panel__body" hidden={folded}>
        <Tabs<K> idPrefix={idPrefix} tabs={tabs} active={active} onChange={onChange} />
        {children}
      </div>
    </aside>
  );
}
