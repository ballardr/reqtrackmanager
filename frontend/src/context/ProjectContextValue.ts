/**
 * Module: context/ProjectContextValue
 *
 * The `ProjectContext` object and its value type, split out of
 * TerminologyContext.tsx so that file can keep exporting only components/
 * hooks (`TerminologyProvider`, `useTerm`, `useTermPlural`) — a file mixing
 * component and non-component exports breaks Fast Refresh
 * (react-refresh/only-export-components). Storybook stories import
 * `ProjectContext` from here directly to supply terminology overrides via
 * `<ProjectContext.Provider value={...}>` without mocking the project-fetch
 * effect.
 */
import { createContext } from "react";

export interface ProjectContextValue {
  terminology: Record<string, string>;
}

export const ProjectContext = createContext<ProjectContextValue>({ terminology: {} });
