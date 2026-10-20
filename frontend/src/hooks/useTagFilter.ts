/**
 * Module: hooks/useTagFilter
 *
 * The state behind a list's tag filter: the chosen tag names and whether a record needs any or
 * all of them. A list page keeps this beside its other filters, renders `TagFilterField` with it
 * and adds `query` to its list read, so the server (not the browser) narrows the list.
 */
import { useMemo, useState } from "react";

import { tagQuery } from "../api/tags";

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
  const [tags, setTags] = useState<string[]>([]);
  const [mode, setMode] = useState<"any" | "all">("any");
  const query = useMemo(() => tagQuery(tags, mode), [tags, mode]);
  return { tags, mode, setTags, setMode, query, active: tags.length > 0 };
}
