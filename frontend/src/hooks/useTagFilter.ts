/**
 * Module: hooks/useTagFilter
 *
 * The state behind a list's tag filter: the chosen tag names and whether a record needs any or
 * all of them. A list page keeps this beside its other filters, renders `TagFilterField` with it
 * and adds `query` to its list read, so the server (not the browser) narrows the list. The choice lives in
 * the URL (`tag`, `tag_mode`) with the list's other filters, so the list comes back filtered after a visit
 * to a record (see `useUrlFilter`). Needs a router.
 */
import { useMemo } from "react";

import { tagQuery } from "../api/tags";
import { useUrlChoice, useUrlList } from "./useUrlFilter";

const MODES = ["any", "all"] as const;

export interface TagFilterState {
  tags: string[];
  mode: "any" | "all";
  setTags: (tags: string[]) => void;
  setMode: (mode: "any" | "all") => void;
  /** `tag=a&tag=b&tag_mode=any`, or an empty string when no tag is chosen. */
  query: string;
  active: boolean;
}

/** Holds a list's tag filter. */
export function useTagFilter(): TagFilterState {
  const [tags, setTags] = useUrlList("tag");
  const [chosenMode, setChosenMode] = useUrlChoice("tag_mode", MODES);
  const mode = chosenMode || "any";
  const setMode = (next: "any" | "all") => setChosenMode(next === "any" ? "" : next);
  const query = useMemo(() => tagQuery(tags, mode), [tags, mode]);
  return { tags, mode, setTags, setMode, query, active: tags.length > 0 };
}
