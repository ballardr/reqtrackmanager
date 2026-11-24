/**
 * Module: components/ListPageLayout
 *
 * The one layout for a list page with a side filter panel (docs/ux-style-guide.md, "Pattern: filter panel
 * placement"). The title, its actions and the list share the left column and the filter panel fills the right
 * column from the title's row down. Anything above the list (a scoring-model switcher, a tab strip, a banner) is
 * part of `children`, so it cannot push the filter panel down.
 *
 * A list of records passes `records` and the layout adds the shared Export and Import menu. A list whose columns a
 * person can choose passes `columnChooser` (from `useOptionalColumns`), drawn beside the actions menu as a view
 * control, never as a second primary button.
 *
 * It keeps the list's place ("Pattern: list position"): scroll offset and loaded row count are saved on unmount
 * and restored on return, so a page passes only `ready` and, if paginated, `loadedRows`.
 *
 * The filter panel collapses with its round header toggle (`FilterCollapseContext`): the list takes the full
 * width and a "Filters" button on the title row expands it. The state belongs to the page and survives a view
 * change; collapsing never clears a filter. Narrow viewports use one column: title, filter, list. Pages whose
 * table is too wide for a side panel keep `FilterPanel layout="top"` and do not use this component.
 */
import { PanelTopOpen } from "lucide-react";
import { useMemo, useState, type HTMLAttributes, type ReactNode } from "react";

import { FilterCollapseContext } from "../context/FilterCollapseContext";
import { useCurrentNavLabelOverride } from "../context/NavLabelValue";
import { t } from "../i18n/strings";

import { useListPosition } from "../hooks/useListPosition";
import type { ActionMenuItem } from "./ActionMenu";
import { ListActions, ListActionsMenu, ListMenuItems, type RecordListActions } from "./ListActions";

const strings = t();

/**
 * @param title The page heading (text or node); rendered as the page's `h1`. A name the project or organisation gave the page's navigation entry replaces it.
 * @param actions Page-level actions beside the title (a New button).
 * @param records The record type and filters of the list: adds the shared Export and Import controls (an array when
 *   the list shows several kinds at once, each with a `kindLabel`).
 * @param menuItems The page's other actions (folders, an interchange file, a link to a related page): rows of the one
 *   actions menu, ahead of the export and import items. A page has one primary button in `actions` and this menu, never a row of buttons.
 * @param columnChooser The column chooser (`useOptionalColumns`' `chooser`), shown after the actions menu; null or omitted when the list has none.
 * @param tabs A tab strip (`Tabs`) shown under the title and actions; the list column is then its panel.
 * @param filter The `FilterPanel` (side layout) for the list.
 * @param ready False while the list's rows are loading (default true): the position is saved and restored only once rows exist.
 * @param loadedRows Rows currently loaded by a paginated list ("Show more"), so they can be reloaded on return.
 * @param contentProps Attributes for the list column, e.g. `tabPanelProps(...)` when `tabs` is given.
 * @param children Everything else in the list column: switchers, chips, the list itself.
 */
export function ListPageLayout({
  title, actions, menuItems, records, columnChooser, tabs, filter, ready = true, loadedRows, contentProps, children,
}: {
  title: ReactNode;
  actions?: ReactNode;
  menuItems?: ActionMenuItem[];
  records?: RecordListActions | RecordListActions[];
  columnChooser?: ReactNode;
  tabs?: ReactNode;
  filter: ReactNode;
  ready?: boolean;
  loadedRows?: number;
  contentProps?: HTMLAttributes<HTMLDivElement>;
  children: ReactNode;
}) {
  useListPosition({ ready, loaded: loadedRows });
  const navName = useCurrentNavLabelOverride();
  const [filterHidden, setFilterHidden] = useState(false);
  const collapse = useMemo(() => ({ collapsed: filterHidden, toggle: () => setFilterHidden((hidden) => !hidden) }), [filterHidden]);
  return (
    <div className={filterHidden ? "list-page list-page--filter-collapsed" : "list-page"}>
      <div className="stack list-page__header">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <h1 style={{ margin: 0 }}>{navName ?? title}</h1>
          <div className="row" style={{ alignItems: "center" }}>
            {actions}
            {(records || (menuItems && menuItems.length > 0)) && (
              <ListActionsMenu>
                {menuItems && menuItems.length > 0 && <ListMenuItems items={menuItems} />}
                {records && [records].flat().map((one) => <ListActions key={one.recordType} {...one} />)}
              </ListActionsMenu>
            )}
            {columnChooser}
            {filterHidden && (
              <button type="button" className="btn row" aria-expanded={false} onClick={collapse.toggle} style={{ flexWrap: "nowrap" }}>
                <PanelTopOpen size={16} aria-hidden="true" />
                {strings.common.filters}
              </button>
            )}
          </div>
        </div>
        {tabs}
      </div>
      <div {...contentProps} className="stack list-page__content">{children}</div>
      {/* After the list in the DOM (the list comes first for keyboard and screen-reader users); the grid areas place it. */}
      <div className="list-page__filter" hidden={filterHidden}>
        <FilterCollapseContext.Provider value={collapse}>{filter}</FilterCollapseContext.Provider>
      </div>
    </div>
  );
}
