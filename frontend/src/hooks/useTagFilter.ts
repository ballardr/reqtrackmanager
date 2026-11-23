/**
 * Module: hooks/useTagFilter
 *
 * The state behind a list's tag and component filters: the chosen tag names, whether a record needs any or all of
 * them, the components and categories it must sit in (any of them), and the external systems (any of them) and key
 * text it must be referenced by. A list page keeps this beside its other filters, renders `TagFilterField` with it
 * and adds `query` to its list read, so the server narrows the list. The choice lives in the URL (`tag`,
 * `tag_mode`, `in_component`, `in_category`, `ref_system`, `ref_key`; see `useUrlFilter`). Needs a router.
 */
import { useMemo } from "react";

import { appendReferenceParams } from "../api/externalReferences";
import { appendPlacementParams } from "../api/placements";
import { tagQuery, type TagListFilters } from "../api/tags";
import { useUrlChoice, useUrlList, useUrlText } from "./useUrlFilter";

const MODES = ["any", "all"] as const;

export interface TagFilterState {
  tags: string[];
  mode: "any" | "all";
  setTags: (tags: string[]) => void;
  setMode: (mode: "any" | "all") => void;
  /** The components a record may sit in (a record in any of them, or in any chosen category, matches). */
  components: string[];
  categories: string[];
  setComponents: (ids: string[]) => void;
  setCategories: (ids: string[]) => void;
  /** The external systems (by name) a record must have a reference in (any of them). */
  referenceSystems: string[];
  /** A fragment of the external key a record's reference must contain; empty for any key. */
  referenceKey: string;
  setReferenceSystems: (names: string[]) => void;
  setReferenceKey: (key: string) => void;
  /** `tag=a&tag=b&tag_mode=any&component_id=…&external_system=…`, or an empty string when nothing is chosen. */
  query: string;
  /** Whether any tag, component, category, external system or key is chosen. */
  active: boolean;
  /** The filters as a list API takes them (`tags`, `tag_mode`, `component_ids`, `category_ids`, `external_systems`, `external_key`). */
  listFilters: TagListFilters;
}

/** Holds a list's tag filter. */
export function useTagFilter(): TagFilterState {
  const [tags, setTags] = useUrlList("tag");
  const [chosenMode, setChosenMode] = useUrlChoice("tag_mode", MODES);
  const mode = chosenMode || "any";
  const setMode = (next: "any" | "all") => setChosenMode(next === "any" ? "" : next);
  const [components, setComponents] = useUrlList("in_component");
  const [categories, setCategories] = useUrlList("in_category");
  const [referenceSystems, setReferenceSystems] = useUrlList("ref_system");
  const [referenceKey, setReferenceKey] = useUrlText("ref_key");
  const query = useMemo(() => {
    const params = new URLSearchParams(tagQuery(tags, mode));
    appendPlacementParams(params, { component_ids: components, category_ids: categories });
    appendReferenceParams(params, { external_systems: referenceSystems, external_key: referenceKey });
    return params.toString();
  }, [tags, mode, components, categories, referenceSystems, referenceKey]);
  const listFilters = useMemo<TagListFilters>(
    () => ({
      tags, tag_mode: mode, component_ids: components, category_ids: categories, external_systems: referenceSystems,
      external_key: referenceKey,
    }),
    [tags, mode, components, categories, referenceSystems, referenceKey],
  );
  return {
    tags, mode, setTags, setMode, components, categories, setComponents, setCategories, referenceSystems, referenceKey,
    setReferenceSystems, setReferenceKey, query,
    active: tags.length > 0 || components.length > 0 || categories.length > 0 || referenceSystems.length > 0 || referenceKey.trim() !== "",
    listFilters,
  };
}
