/**
 * Module: components/TagFilterField
 *
 * The tag filter of a list's `FilterPanel`: a dropdown of the project's tags (tick any number)
 * and, once two or more are ticked, whether a record needs any or all of them. The list page
 * owns the state (`useTagFilter`) and sends it to the server.
 *
 * It lists the vocabulary the project offers; a tag still used by records but no longer in the
 * list can be found by typing it on the record, not here. Renders nothing while the project has
 * no tags, so a project that never tags sees no new control.
 */
import { useEffect, useState } from "react";

import { recordTagsApi, type RecordTagsApi, type TagChipData } from "../api/tags";
import type { TagFilterState } from "../hooks/useTagFilter";
import { useStrings } from "../context/TerminologyContext";
import { FilterField } from "./FilterPanel";
import { MultiSelectDropdown } from "./MultiSelectDropdown";

/**
 * @param projectId The project whose tags are offered.
 * @param filter The list's tag filter state (`useTagFilter`).
 * @param api Injectable calls (stories pass a fake).
 */
export function TagFilterField({
  projectId, filter, api = recordTagsApi,
}: { projectId: string; filter: TagFilterState; api?: RecordTagsApi }) {
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

  if (tags.length === 0) return null;
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
        <FilterField label={strings.tags.filter.matchLabel}>
          <select
            className="input"
            aria-label={strings.tags.filter.matchLabel}
            value={filter.mode}
            onChange={(e) => filter.setMode(e.target.value as "any" | "all")}
          >
            <option value="any">{strings.tags.filter.any}</option>
            <option value="all">{strings.tags.filter.all}</option>
          </select>
        </FilterField>
      )}
    </>
  );
}
