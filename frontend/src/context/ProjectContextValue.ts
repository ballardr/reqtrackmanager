/**
 * Module: context/ProjectContextValue
 *
 * The `ProjectContext` object and its value type, kept apart from TerminologyContext.tsx so that file exports only
 * components and hooks (`TerminologyProvider`, `useTerm`, `useTermPlural`); a file mixing both breaks Fast Refresh
 * (`react-refresh/only-export-components`). Storybook stories import `ProjectContext` from here to supply terminology
 * overrides through `<ProjectContext.Provider value={...}>` without mocking the project-fetch effect.
 */
import { createContext } from "react";

export interface ProjectContextValue {
  terminology: Record<string, string>;
  /** The current project's code (qualifies record codes); `null` outside a project. */
  projectCode?: string | null;
  /** Whether the project's organisation shows the project code on every record code. */
  enforceCodeEverywhere?: boolean;
  /** The current project's organisation, and its code (qualifies the codes of records the organisation owns). */
  organizationId?: string | null;
  organizationCode?: string | null;
}

export const ProjectContext = createContext<ProjectContextValue>({ terminology: {} });
