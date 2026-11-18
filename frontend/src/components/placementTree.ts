/**
 * Module: components/placementTree
 *
 * The project's component and category tree as `TreeSelect` nodes, and the mapping between a ticked node and a place.
 * Shared by the record picker (`PlacementPicker`), the list filter (`ComponentFilterField`) and any dialog that narrows
 * records by component, so every control shows the same collapsible tree: each component with its categories beneath it.
 *
 * A component and one of its categories are different places (a component alone, or the component narrowed to a
 * category), so each is its own node and ticking one never ticks the other.
 */
import type { PlacementPair, PlacementTree } from "../api/placements";
import type { TreeSelectNode } from "./TreeSelect";

const COMPONENT_PREFIX = "component:";
const CATEGORY_PREFIX = "category:";

/** The node id of a component. */
export function componentNodeId(componentId: string): string {
  return COMPONENT_PREFIX + componentId;
}

/** The node id of a category. */
export function categoryNodeId(categoryId: string): string {
  return CATEGORY_PREFIX + categoryId;
}

/**
 * The tree as nodes: a node per component with a child per category of it, in the tree's own order.
 *
 * @param tree The project's components and categories.
 * @returns Root nodes (the components); a category's `pathLabel` is `Component / Category`.
 */
export function placementNodes(tree: PlacementTree): TreeSelectNode[] {
  return tree.components.map((component) => ({
    id: componentNodeId(component.id),
    label: component.name,
    children: tree.categories
      .filter((category) => category.component_id === component.id)
      .map((category) => ({
        id: categoryNodeId(category.id),
        label: category.name,
        pathLabel: `${component.name} / ${category.name}`,
        children: [],
      })),
  }));
}

/** The node id of a place: its category when it has one, else its component. */
export function placeNodeId(place: PlacementPair): string {
  return place.category_id ? categoryNodeId(place.category_id) : componentNodeId(place.component_id);
}

/**
 * The places that ticked node ids stand for.
 *
 * @param ids Node ids (`TreeSelect`'s `selectedIds`).
 * @param tree The tree the ids were drawn from; an id it does not hold (a deleted category) is dropped.
 */
export function placesOfNodeIds(ids: readonly string[], tree: PlacementTree): PlacementPair[] {
  const places: PlacementPair[] = [];
  for (const id of ids) {
    if (id.startsWith(COMPONENT_PREFIX)) {
      const componentId = id.slice(COMPONENT_PREFIX.length);
      if (tree.components.some((c) => c.id === componentId)) places.push({ component_id: componentId, category_id: null });
    } else if (id.startsWith(CATEGORY_PREFIX)) {
      const category = tree.categories.find((c) => c.id === id.slice(CATEGORY_PREFIX.length));
      if (category) places.push({ component_id: category.component_id, category_id: category.id });
    }
  }
  return places;
}
