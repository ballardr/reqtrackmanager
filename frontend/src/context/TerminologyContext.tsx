import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { api } from "../api/client";
import type { Organization, Project } from "../api/types";

export type TerminologyKey = "project" | "stage" | "component" | "category" | "requirement" | "change_request";

const DEFAULT_TERMS: Record<TerminologyKey, string> = {
  project: "Project",
  stage: "Stage",
  component: "Component",
  category: "Category",
  requirement: "Requirement",
  change_request: "Change Request",
};

interface ProjectContextValue {
  terminology: Record<string, string>;
  orgLogoFileId: string | null;
}

const ProjectContext = createContext<ProjectContextValue>({ terminology: {}, orgLogoFileId: null });

/**
 * Provides the current project's terminology overrides (C-C-03) and its
 * owning organisation's logo (U-C-02) to everything rendered underneath it.
 * Fetches once per `projectId` change; outside of a project context
 * (projectId null) terms resolve to their default English word and no logo
 * is shown.
 */
export function TerminologyProvider({ projectId, children }: { projectId: string | null; children: ReactNode }) {
  const [value, setValue] = useState<ProjectContextValue>({ terminology: {}, orgLogoFileId: null });

  useEffect(() => {
    if (!projectId) {
      setValue({ terminology: {}, orgLogoFileId: null });
      return;
    }
    api.get<Project>(`/api/v1/projects/${projectId}`).then(async (project) => {
      const org = await api.get<Organization>(`/api/v1/orgs/${project.organization_id}`);
      setValue({ terminology: project.terminology ?? {}, orgLogoFileId: org.logo_file_id });
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

/** Naively pluralises a resolved term (adds "s") — good enough for the
 * regular nouns this app ships by default; a project overriding a term
 * with an irregular plural (e.g. "Story"/"Stories") would need to type the
 * plural form as its override to read correctly everywhere it's used. */
export function useTermPlural(key: TerminologyKey): string {
  return `${useTerm(key)}s`;
}

/** The current project's organisation's logo file id, if one is set
 * (U-C-02) — null outside of a project context or if no logo is uploaded. */
export function useOrgLogoFileId(): string | null {
  return useContext(ProjectContext).orgLogoFileId;
}
