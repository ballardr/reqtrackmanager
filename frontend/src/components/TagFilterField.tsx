/**
 * Module: components/TagFilterField
 *
 * The tag filter of a list's `FilterPanel`: a dropdown of the project's tags (tick any number)
 * and, once two or more are ticked, whether a record needs any or all of them. The list page
 * owns the state (`useTagFilter`) and sends it to the server. It is also where every list gets its component
 * filter (`ComponentFilterField`), since both narrow the same rows through one server filter; a page that has
 * its own component filter (the requirements list) passes `components={false}`.
 *
 * It lists the vocabulary the project offers; a tag still used by records but no longer in the
 * list can be found by typing it on the record, not here. Renders nothing while the project has
 * no tags, so a project that never tags sees no new control.
 */
import { useEffect, useState } from "react";

import { recordTagsApi, type RecordTagsApi, type TagChipData } from "../api/tags";
import type { TagFilterState } from "../hooks/useTagFilter";
import { useStrings } from "../context/TerminologyContext";
import { ComponentFilterField } from "./ComponentFilterField";
import { FilterField } from "./FilterPanel";
import { FilterSelect } from "./FilterSelect";
import { MultiSelectDropdown } from "./MultiSelectDropdown";

/**
 * @param projectId The project whose tags are offered.
 * @param filter The list's tag filter state (`useTagFilter`).
 * @param api Injectable calls (stories pass a fake).
 * @param components Whether to offer the component filter too (default true).
 */
export function TagFilterField({
  projectId, filter, api = recordTagsApi, components = true,
}: { projectId: string; filter: TagFilterState; api?: RecordTagsApi; components?: boolean }) {
  const strings = useStrings();
  const [tags, setTags] = useState<TagChipData[]>([]);

  useEffect(() => {
    let active = true;
    api.vocabulary(projectId)
      .then((vocabulary) => active && setTags(vocabulary.tags))
      .catch(() => active && setTags([]));
    return () => {
      active = false;
    };
  }, [api, projectId]);

  const componentFilter = components ? <ComponentFilterField projectId={projectId} filter={filter} /> : null;
  if (tags.length === 0) return componentFilter;
  const chosen = new Set(filter.tags.map((t) => t.toLowerCase()));
  return (
    <>
      <FilterField label={strings.tags.filter.label}>
        <MultiSelectDropdown
          triggerLabel={strings.tags.filter.label}
          emptyLabel={strings.tags.filter.choose}
          options={tags.map((tag) => {
            const checked = chosen.has(tag.name.toLowerCase());
            return {
              value: tag.id,
              label: tag.name,
              checked,
              optionLabel: tag.name,
              onToggle: () => filter.setTags(
                checked ? filter.tags.filter((t) => t.toLowerCase() !== tag.name.toLowerCase()) : [...filter.tags, tag.name],
              ),
            };
          })}
        />
      </FilterField>
      {filter.tags.length > 1 && (
        <FilterSelect
          label={strings.tags.filter.matchLabel}
          value={filter.mode}
          onChange={filter.setMode}
          options={[{ value: "any", label: strings.tags.filter.any }, { value: "all", label: strings.tags.filter.all }]}
        />
      )}
      {componentFilter}
    </>
  );
}
