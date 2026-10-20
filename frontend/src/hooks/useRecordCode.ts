import { useCallback, useContext } from "react";

import { AuthContext } from "../context/AuthContextValue";
import { ProjectContext } from "../context/ProjectContextValue";
import { formatLabelCode, formatRecordCode, type RecordCodeContext } from "../utils/recordCode";

/** The `ui_preferences` key holding the viewer's choice to see project codes inside their own project. */
export const SHOW_PROJECT_CODE_PREFERENCE = "show_project_code";

export interface RecordCodeFormatters {
  /** Formats a record code (`REQ-001`); pass the owning project's code for a record in another project. */
  code: (code: string, ownerProjectCode?: string | null) => string;
  /** Formats the leading code of a summary label (`REQ-001 Title`). */
  label: (label: string, ownerProjectCode?: string | null) => string;
}

/**
 * Returns the formatters that apply the platform's one record-code display rule
 * (`utils/recordCode.ts`) for the project the viewer is in and the viewer's preference.
 */
export function useRecordCode(): RecordCodeFormatters {
  const { projectCode, enforceCodeEverywhere } = useContext(ProjectContext);
  // Read the auth context directly (not `useAuth`) so a record code still renders, with the
  // default preference, where no auth provider exists (a component rendered on its own).
  const stored = useContext(AuthContext)?.user?.ui_preferences[SHOW_PROJECT_CODE_PREFERENCE];
  const preferred = typeof stored === "boolean" ? stored : true;
  const code = projectCode ?? null;
  const enforced = enforceCodeEverywhere ?? false;
  const ctx = useCallback((): RecordCodeContext => ({ currentProjectCode: code, enforced, preferred }), [code, enforced, preferred]);
  return {
    code: useCallback((c, owner) => formatRecordCode(c, ctx(), owner), [ctx]),
    label: useCallback((l, owner) => formatLabelCode(l, ctx(), owner), [ctx]),
  };
}
