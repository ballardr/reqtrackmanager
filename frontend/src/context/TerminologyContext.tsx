import { useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api } from "../api/client";
import type { Project } from "../api/types";
import { DEFAULT_TERMS, pluralize, resolveTerminologyDeep, type TerminologyKey } from "../i18n/terminology";
import { t, type Strings } from "../i18n/strings";
import { ProjectContext, type ProjectContextValue } from "./ProjectContextValue";

export type { TerminologyKey };

/**
 * Provides the current project's terminology overrides (C-C-03) to
 * everything rendered underneath it. Fetches once per `projectId` change;
 * outside of a project context (projectId null) terms resolve to their
 * default English word. The current project's *organisation* logo/title/
 * accent colour is a separate concern with different resolution rules —
 * see `BrandingContext`.
 */
export function TerminologyProvider({ projectId, children }: { projectId: string | null; children: ReactNode }) {
  const [value, setValue] = useState<ProjectContextValue>({ terminology: {} });

  useEffect(() => {
    if (!projectId) {
      setValue({ terminology: {} });
      return;
    }
    api.get<Project>(`/api/v1/projects/${projectId}`).then((project) => {
      setValue({ terminology: project.terminology ?? {} });
    });
  }, [projectId]);

  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>;
}

/** Resolves one standard term to the current project's override, or its
 * default English word if none is set (C-C-03). */
export function useTerm(key: TerminologyKey): string {
  const { terminology } = useContext(ProjectContext);
  return terminology[key] || DEFAULT_TERMS[key];
}

/** Pluralises (see `pluralize`) and capitalises a resolved term — every
 * current call site uses the plural as a standalone heading or nav label
 * (the first word of its own text), never mid-phrase, so capitalising here
 * once covers all of them rather than at each site. */
export function useTermPlural(key: TerminologyKey): string {
  const plural = pluralize(useTerm(key));
  return plural.charAt(0).toUpperCase() + plural.slice(1);
}

/**
 * Returns the UI string table (`strings.ts`) with every terminology token
 * (C-C-03) substituted for the current project's resolved term, or its
 * English default outside a project context / where no override is set.
 * This is the terminology-aware replacement for calling `t()` directly —
 * any component whose strings include a `{requirement}`/`{Stage}`/etc.
 * token must use this hook, not `t()`, or the raw token renders literally.
 * Strings with no token in them read identically either way.
 */
export function useStrings(): Strings {
  const { terminology } = useContext(ProjectContext);
  return useMemo(() => resolveTerminologyDeep(t(), terminology), [terminology]);
}
