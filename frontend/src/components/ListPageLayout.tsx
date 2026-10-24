/**
 * Module: components/ListPageLayout
 *
 * The one layout for a list page with a side filter panel (docs/ux-style-guide.md, "Pattern: filter panel
 * placement"). The page title, its actions and the list share the left column and the filter panel fills the
 * right column from the title's own row down, so the filter's top edge lines up with the title on every list
 * page. Anything a page used to put above the list (a scoring-model switcher, a view tab strip, a banner)
 * is part of `children`, in the list column, so it can never push the filter panel down.
 *
 * A list of records passes `records` and the layout adds the shared Export and Import menu beside the page's
 * own actions (docs/ux-style-guide.md, "Pattern: list actions (export and import)").
 *
 * The layout also keeps the list's place (docs/ux-style-guide.md, "Pattern: list position"): it saves the scroll
 * offset and the loaded row count when the page unmounts and restores them on return, so a page passes only
 * `ready` and, if paginated, `loadedRows`.
 *
 * Narrow viewports collapse to one column in the order title, filter, list (the filter is a collapsed
 * accordion there). Pages whose table is too wide for a side panel keep `FilterPanel layout="top"` and do
 * not use this component.
 */
import type { HTMLAttributes, ReactNode } from "react";

import { useListPosition } from "../hooks/useListPosition";
import { ListActions, ListActionsMenu, type RecordListActions } from "./ListActions";

/**
 * @param title The page heading (text or node); rendered as the page's `h1`.
 * @param actions Page-level actions beside the title (a New button).
 * @param records The record type and filters of the list: adds the shared Export and Import controls (an array when
 *   the list shows several kinds at once, each with a `kindLabel`).
 * @param tabs A tab strip (`Tabs`) shown under the title and actions; the list column is then its panel.
 * @param filter The `FilterPanel` (side layout) for the list.
 * @param ready False while the list's rows are loading (default true): the position is saved and restored only once rows exist.
 * @param loadedRows Rows currently loaded by a paginated list ("Show more"), so they can be reloaded on return.
 * @param contentProps Attributes for the list column, e.g. `tabPanelProps(...)` when `tabs` is given.
 * @param children Everything else in the list column: switchers, chips, the list itself.
 */
export function ListPageLayout({
  title, actions, records, tabs, filter, ready = true, loadedRows, contentProps, children,
}: {
  title: ReactNode;
  actions?: ReactNode;
  records?: RecordListActions | RecordListActions[];
  tabs?: ReactNode;
  filter: ReactNode;
  ready?: boolean;
  loadedRows?: number;
  contentProps?: HTMLAttributes<HTMLDivElement>;
  children: ReactNode;
}) {
  useListPosition({ ready, loaded: loadedRows });
  return (
    <div className="list-page">
      <div className="stack list-page__header">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <h1 style={{ margin: 0 }}>{title}</h1>
          {records ? (
            <div className="row" style={{ alignItems: "center" }}>
              {actions}
              <ListActionsMenu>
                {[records].flat().map((one) => <ListActions key={one.recordType} {...one} />)}
              </ListActionsMenu>
            </div>
          ) : actions}
        </div>
        {tabs}
      </div>
      <div {...contentProps} className="stack list-page__content">{children}</div>
      {/* After the list in the DOM (the list comes first for keyboard and screen-reader users); the grid areas place it. */}
      <div className="list-page__filter">{filter}</div>
    </div>
  );
}
