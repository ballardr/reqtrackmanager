/**
 * Module: modules/architecture/architectureTabs
 *
 * The tabs of the System Architecture page (`SystemArchitecturePage`) and the addresses that open them.
 *
 * Responsibilities:
 * - `ARCHITECTURE_TABS`: each tab's key, label and the module sub-component that must be enabled to show it.
 * - `architectureTabPath`: the one place that builds a tab's address, used by links, redirects and `module.ts`.
 * - `ArchitectureListChrome`: what the page hands the list it shows (the tab strip and its panel attributes), so
 *   each list is still an ordinary `ListPageLayout` page that works without the shell (stories, a future embed).
 *
 * Design decisions:
 * - The tab is a query parameter on one route, so every tab's own filters stay in the address beside it and the
 *   shared list-position and back-link mechanisms keep working per tab.
 */
import type { HTMLAttributes, ReactNode } from "react";

/** A tab of the System Architecture page. */
export type ArchitectureTab = "elements" | "connections" | "diagrams";

/** The page heading every tab shares. */
export const ARCHITECTURE_PAGE_TITLE = "System Architecture";

/** Tab definitions in display order; `subComponent` is the key the module registers for that list. */
export const ARCHITECTURE_TABS: readonly { key: ArchitectureTab; label: string; subComponent: string }[] = [
  { key: "elements", label: "Elements", subComponent: "architecture_element" },
  { key: "connections", label: "Connections", subComponent: "architecture_connection" },
  { key: "diagrams", label: "Diagrams", subComponent: "architecture_diagram" },
];

/**
 * The address of one tab of a project's System Architecture page.
 *
 * @param projectId The project.
 * @param tab The tab to open.
 * @returns The path with the tab in its query.
 */
export function architectureTabPath(projectId: string, tab: ArchitectureTab): string {
  return `/projects/${projectId}/modules/architecture?tab=${tab}`;
}

/** What the System Architecture page gives a list: the tab strip and the attributes of the list column as its panel. */
export interface ArchitectureListChrome {
  tabs: ReactNode;
  contentProps: HTMLAttributes<HTMLDivElement>;
}

/**
 * The address of a diagram's own editor.
 *
 * @param projectId The project the diagram belongs to.
 * @param kind `block` or `state_machine`.
 * @param id The diagram's id.
 */
export function diagramEditorPath(projectId: string, kind: "block" | "state_machine", id: string): string {
  return `/projects/${projectId}/modules/architecture/${kind === "block" ? "diagrams" : "state-machine-diagrams"}/${id}`;
}
