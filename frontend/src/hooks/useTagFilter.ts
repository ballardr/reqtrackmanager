/**
 * Module: hooks/useTagFilter
 *
 * The state behind a list's tag and component filters: the chosen tag names, whether a record needs any or
 * all of them, and the components and categories it must sit in (any of them). A list page keeps this beside its other filters, renders `TagFilterField` with it
 * and adds `query` to its list read, so the server (not the browser) narrows the list. The choice lives in
 * the URL (`tag`, `tag_mode`, `in_component`, `in_category`) with the list's other filters, so the list comes back filtered after a visit
 * to a record (see `useUrlFilter`). Needs a router.
 */
import { useMemo } from "react";

import { appendPlacementParams } from "../api/placements";
import { tagQuery, type TagListFilters } from "../api/tags";
import { useUrlChoice, useUrlList } from "./useUrlFilter";

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
  /** `tag=a&tag=b&tag_mode=any&component_id=…`, or an empty string when nothing is chosen. */
  query: string;
  /** Whether any tag, component or category is chosen. */
  active: boolean;
  /** The filters as a list API takes them (`tags`, `tag_mode`, `component_ids`, `category_ids`). */
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
  const query = useMemo(() => {
    const params = new URLSearchParams(tagQuery(tags, mode));
    appendPlacementParams(params, { component_ids: components, category_ids: categories });
    return params.toString();
  }, [tags, mode, components, categories]);
  const listFilters = useMemo<TagListFilters>(
    () => ({ tags, tag_mode: mode, component_ids: components, category_ids: categories }),
    [tags, mode, components, categories],
  );
  return {
    tags, mode, setTags, setMode, components, categories, setComponents, setCategories, query,
    active: tags.length > 0 || components.length > 0 || categories.length > 0, listFilters,
  };
}
