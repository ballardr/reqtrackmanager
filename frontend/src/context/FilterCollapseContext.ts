/**
 * Module: context/FilterCollapseContext
 *
 * Lets a list page's layout (`ListPageLayout`) hand the filter panel inside it the state and toggle of its
 * collapse, so the `FilterPanel` can draw the toggle in its own header without every page threading props through.
 * `null` outside a layout: the panel then has no toggle and is always open.
 */
import { createContext } from "react";

export interface FilterCollapse {
  /** True while the panel is collapsed to its header bar above the list. */
  collapsed: boolean;
  toggle: () => void;
}

export const FilterCollapseContext = createContext<FilterCollapse | null>(null);
