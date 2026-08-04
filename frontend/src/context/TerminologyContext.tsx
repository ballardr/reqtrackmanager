import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { api } from "../api/client";
import type { Project } from "../api/types";

export type TerminologyKey = "project" | "stage" | "component" | "category" | "requirement" | "change_request";

// Lower case: these are substituted mid-phrase ("New requirement") as often
// as they're used standalone (a nav label, a page heading) — `useTerm`
// returns the raw lower-case form for the former; `useTermPlural` (below)
// capitalises, since every current standalone usage is plural.
const DEFAULT_TERMS: Record<TerminologyKey, string> = {
  project: "project",
  stage: "stage",
  component: "component",
  category: "category",
  requirement: "requirement",
  change_request: "change request",
};

interface ProjectContextValue {
  terminology: Record<string, string>;
}

const ProjectContext = createContext<ProjectContextValue>({ terminology: {} });

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

/** Naively pluralises a resolved term (adds "s") and capitalises it —
 * every current call site uses the plural as a standalone heading or nav
 * label (the first word of its own text), never mid-phrase, so
 * capitalising here once covers all of them rather than at each site.
 * Pluralisation is good enough for the regular nouns this app ships by
 * default; a project overriding a term with an irregular plural (e.g.
 * "Story"/"Stories") would need to type the plural form as its override to
 * read correctly everywhere it's used. */
export function useTermPlural(key: TerminologyKey): string {
  const plural = `${useTerm(key)}s`;
  return plural.charAt(0).toUpperCase() + plural.slice(1);
}
