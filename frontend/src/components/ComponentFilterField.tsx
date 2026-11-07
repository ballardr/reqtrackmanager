/**
 * Module: components/ComponentFilterField
 *
 * The component filter of a list's `FilterPanel`: a dropdown of the project's components and categories (tick any
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
import { MultiSelectDropdown, type MultiSelectOption } from "./MultiSelectDropdown";

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
  const toggle = (list: string[], set: (ids: string[]) => void, id: string) =>
    set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  const options: MultiSelectOption[] = [];
  for (const component of tree.components) {
    options.push({
      value: component.id,
      label: component.name,
      checked: filter.components.includes(component.id),
      optionLabel: component.name,
      onToggle: () => toggle(filter.components, filter.setComponents, component.id),
    });
    for (const category of tree.categories.filter((c) => c.component_id === component.id)) {
      const label = `${component.name} / ${category.name}`;
      options.push({
        value: category.id,
        label,
        checked: filter.categories.includes(category.id),
        optionLabel: label,
        onToggle: () => toggle(filter.categories, filter.setCategories, category.id),
      });
    }
  }
  return (
    <FilterField label={strings.placements.filterLabel} help={strings.help.recordComponentsFilter}>
      <MultiSelectDropdown
        triggerLabel={strings.placements.filterLabel}
        emptyLabel={strings.placements.choose}
        options={options}
        filterable
        summaryLimit={2}
      />
    </FilterField>
  );
}
