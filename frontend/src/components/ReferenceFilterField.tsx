/**
 * Module: components/ReferenceFilterField
 *
 * The external reference filter of a list's `FilterPanel`: a dropdown of the project's external systems (tick any
 * number) and a text box for part of the key. A record matches when it has a reference in any ticked system whose key
 * contains the text (the same reference must satisfy both when both are given). The list page owns the state
 * (`useTagFilter`) and sends it to the server. `TagFilterField` renders it, so every list with a tag filter has it.
 *
 * Renders nothing while the project has no external system, so a project that never uses references sees no new control.
 */
import { useEffect, useState } from "react";

import { referenceFilterApi, type ReferenceFilterApi } from "../api/externalReferences";
import { useStrings } from "../context/TerminologyContext";
import type { TagFilterState } from "../hooks/useTagFilter";
import { InlineTextInput } from "./FormFields";
import { FilterField } from "./FilterPanel";
import { MultiSelectDropdown } from "./MultiSelectDropdown";

/**
 * @param projectId The project whose systems are offered.
 * @param filter The list's filter state (`useTagFilter`).
 * @param api Injectable calls (stories pass a fake).
 */
export function ReferenceFilterField({
  projectId, filter, api = referenceFilterApi,
}: { projectId: string; filter: TagFilterState; api?: ReferenceFilterApi }) {
  const strings = useStrings();
  const [systems, setSystems] = useState<string[]>([]);

  useEffect(() => {
    let active = true;
    api.systems(projectId)
      .then((names) => active && setSystems(names))
      .catch(() => active && setSystems([]));
    return () => {
      active = false;
    };
  }, [api, projectId]);

  if (systems.length === 0) return null;
  const chosen = new Set(filter.referenceSystems.map((n) => n.toLowerCase()));
  return (
    <>
      <FilterField label={strings.references.filter.label} help={strings.help.referenceFilterSystem}>
        <MultiSelectDropdown
          triggerLabel={strings.references.filter.label}
          emptyLabel={strings.references.filter.choose}
          options={systems.map((name) => {
            const checked = chosen.has(name.toLowerCase());
            return {
              value: name,
              label: name,
              checked,
              optionLabel: name,
              onToggle: () => filter.setReferenceSystems(
                checked ? filter.referenceSystems.filter((n) => n.toLowerCase() !== name.toLowerCase()) : [...filter.referenceSystems, name],
              ),
            };
          })}
        />
      </FilterField>
      <FilterField label={strings.references.filter.keyLabel} help={strings.help.referenceFilterKey}>
        <InlineTextInput
          ariaLabel={strings.references.filter.keyLabel} placeholder={strings.references.filter.keyPlaceholder}
          value={filter.referenceKey} onChange={filter.setReferenceKey} commitOnBlur
        />
      </FilterField>
    </>
  );
}
