import type { MergeConflict } from "../api/types";

/** Each conflict's safe-by-default resolution — preserves whatever's
 * already there unless the caller explicitly opts into overwriting/copying
 * it, so a merge can never surprise-destroy or surprise-duplicate existing
 * data just by being submitted without every choice touched. */
export function defaultResolutions(conflicts: MergeConflict[]): Record<string, string> {
  return Object.fromEntries(
    conflicts.map((c) => [c.id, c.kind === "project" ? "skip" : "keep_existing"]),
  );
}
