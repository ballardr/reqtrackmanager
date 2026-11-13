/**
 * Module: components/ComponentFilterField
 *
 * The component filter of a list's `FilterPanel`: a collapsible tree of the project's components, each with its categories (tick any
 * number); a record matches when it sits in any ticked component or category. The list page owns the state
 * (`useTagFilter`) and sends it to the server. `TagFilterField` renders it, so every list with a tag filter has it.
 *
 * Renders nothing while the project has no components, so a project that never uses them sees no new control.
 */
import { useEffect, useState } from "react";

import { recordPlacementsApi, type PlacementTree, type RecordPlacementsApi } from "../api/placements";
import { useStrings } from "../context/TerminologyContext";
import type { TagFilterState } from "../hooks/useTagFilter";
import { FilterField } from "./FilterPanel";
import { categoryNodeId, componentNodeId, placementNodes, placesOfNodeIds } from "./placementTree";
import { TreeSelect } from "./TreeSelect";

/**
 * @param projectId The project whose tree is offered.
 * @param filter The list's filter state (`useTagFilter`).
 * @param api Injectable calls (stories pass a fake).
 */
export function ComponentFilterField({
  projectId, filter, api = recordPlacementsApi,
}: { projectId: string; filter: TagFilterState; api?: RecordPlacementsApi }) {
  const strings = useStrings();
  const [tree, setTree] = useState<PlacementTree | null>(null);

  useEffect(() => {
    let active = true;
    api.tree(projectId)
      .then((loaded) => active && setTree(loaded))
      .catch(() => active && setTree(null));
    return () => {
      active = false;
    };
  }, [api, projectId]);

  if (!tree || tree.components.length === 0) return null;
  const selected = [...filter.components.map(componentNodeId), ...filter.categories.map(categoryNodeId)];
  const change = (ids: string[]) => {
    const places = placesOfNodeIds(ids, tree);
    filter.setComponents(places.filter((p) => !p.category_id).map((p) => p.component_id));
    filter.setCategories(places.flatMap((p) => (p.category_id ? [p.category_id] : [])));
  };
  return (
    <FilterField label={strings.placements.filterLabel} help={strings.help.recordComponentsFilter}>
      <TreeSelect
        triggerLabel={strings.placements.filterLabel}
        emptyLabel={strings.placements.choose}
        nodes={placementNodes(tree)}
        selectedIds={selected}
        onChange={change}
        searchable
      />
    </FilterField>
  );
}
