/**
 * Module: utils/recordCode
 *
 * The one rule for how a record code is shown: `REQ-001` inside its own project, or the
 * qualified `ACME-REQ-001` once the project code is added. No page decides for itself; pages
 * call `useRecordCode` (hooks/useRecordCode.ts), which feeds this function.
 *
 * Rule: a record outside its own project is always qualified. Inside it, qualified when the
 * organisation enforces it, otherwise per the user's `show_project_code` preference.
 *
 * Dependencies: none.
 */

/** Matches the leading `PREFIX-nnn` code of a summary label (`FND-001 Title`, `SYS-PERF-014 — Name`). */
const LEADING_CODE = /^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+(?=\s|$)/;

export interface RecordCodeContext {
  /** The code of the project the viewer is in, if any. */
  currentProjectCode: string | null;
  /** Whether the organisation shows the project code everywhere. */
  enforced: boolean;
  /** The viewer's `show_project_code` preference (default on). */
  preferred: boolean;
}

/**
 * Formats one record code for display.
 *
 * @param code The record's own code, e.g. `REQ-001`.
 * @param ctx Where the viewer is and how the display is configured.
 * @param ownerProjectCode The code of the project that owns the record; omit for a record in the viewer's own project.
 * @returns The code, qualified with the project code when the rule says so and the project code is known.
 */
export function formatRecordCode(code: string, ctx: RecordCodeContext, ownerProjectCode?: string | null): string {
  const owner = ownerProjectCode ?? ctx.currentProjectCode;
  if (!owner || !code) return code;
  const elsewhere = ownerProjectCode != null && ownerProjectCode !== ctx.currentProjectCode;
  return elsewhere || ctx.enforced || ctx.preferred ? `${owner}-${code}` : code;
}

/**
 * Applies `formatRecordCode` to the leading code of a summary label (`FND-001 Title`); a label
 * with no leading code is returned unchanged.
 */
export function formatLabelCode(label: string, ctx: RecordCodeContext, ownerProjectCode?: string | null): string {
  const match = LEADING_CODE.exec(label);
  if (!match) return label;
  return formatRecordCode(match[0], ctx, ownerProjectCode) + label.slice(match[0].length);
}
