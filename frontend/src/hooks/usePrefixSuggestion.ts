/**
 * Module: hooks/usePrefixSuggestion
 *
 * The server's suggested prefix for a component or category name, asked after the person pauses typing. The rule lives
 * on the server (`services.taxonomy.suggest_prefix`) so the screen, the API, imports and MCP agree; this hook only
 * asks, and discards an answer for a name that is no longer the one typed.
 */
import { useEffect, useState } from "react";

import type { StructureApi, SuggestionRequest } from "../api/structure";

/** How long the name must rest before the server is asked. */
const SUGGESTION_DELAY_MS = 250;

/** The answer to one question, with the name it was asked for. */
export interface PrefixSuggestion {
  name: string;
  prefix: string;
}

/**
 * @param api The structure calls (injectable for stories).
 * @param projectId The project the tree belongs to.
 * @param request What to suggest for; `null` asks nothing (the prefix is fixed or already typed).
 * @returns The latest answer, or `null` before any. Compare `name` with the current name before using it.
 */
export function usePrefixSuggestion(
  api: StructureApi, projectId: string, request: SuggestionRequest | null,
): PrefixSuggestion | null {
  const [answer, setAnswer] = useState<PrefixSuggestion | null>(null);
  const kind = request?.kind;
  const name = request?.name;
  const componentId = request?.componentId;
  const ignore = request?.ignore;

  useEffect(() => {
    if (kind === undefined || name === undefined) return undefined;
    let active = true;
    const timer = setTimeout(() => {
      api.suggestPrefix(projectId, { kind, name, componentId, ignore })
        .then((prefix) => active && setAnswer({ name, prefix }))
        // A failed suggestion leaves the field as it is: the person can still type a prefix.
        .catch(() => undefined);
    }, name.trim() === "" ? 0 : SUGGESTION_DELAY_MS);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [api, projectId, kind, name, componentId, ignore]);

  return answer;
}
