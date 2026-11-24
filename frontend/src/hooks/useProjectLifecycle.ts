/**
 * Module: hooks/useProjectLifecycle
 *
 * The effective lifecycle of one record type in one project, for a record page: which states are turned off and which
 * moves the server allows (`GET /projects/{id}/lifecycles`, one read per page, never one per row).
 *
 * Responsibilities:
 * - Hide a turned-off step from the track (the current step always stays, because a record may sit in a state later
 *   turned off) and aim Promote at the next step that is on (`visibleSteps`, `nextOnPath`).
 * - Answer whether a move is legal now (`canMove`), so an actions-menu row appears exactly where the server accepts
 *   the move.
 *
 * Design decisions: until the configuration is loaded, or when it cannot be (no project, an organisation record, a
 * failed request), every answer is the page's own default, so a page behaves as before and never blocks on this read.
 * The server stays the authority: a move it refuses is reported by the page's existing error handling.
 */
import { useCallback, useState } from "react";

import { lifecyclesApi, type LifecyclesApi, type ProjectLifecycle } from "../api/lifecycles";
import { useLoadOnChange } from "./useLoadOnChange";

/** What a record page reads from the lifecycle configuration. */
export interface EffectiveLifecycle {
  /** The loaded lifecycle, or `null` while unknown. */
  lifecycle: ProjectLifecycle | null;
  /** The states that are off here (empty while unknown). */
  disabled: ReadonlySet<string>;
  /** `steps` without the turned-off ones, except `current`. */
  visibleSteps<T extends { key: string }>(steps: readonly T[], current: string): T[];
  /** The first step after `current` on `path` that is on, or `undefined` at the end. */
  nextOnPath(path: readonly string[], current: string): string | undefined;
  /** `key` when it is on, else the nearest earlier step on `path` that is (where a record that skipped it was last). */
  lastOnPath(path: readonly string[], key: string): string;
  /** Whether a record in `from` may move to `to`; `base` is the answer while the configuration is unknown. */
  canMove(from: string, to: string, base: boolean): boolean;
}

const NONE: ReadonlySet<string> = new Set();

/**
 * @param projectId The record's project; `null` or `undefined` for a record the organisation owns (its full path applies).
 * @param artefactType The registered record type (`pain_point`, `decision`, ...).
 * @param api The calls (the live ones by default); injectable for stories.
 */
export function useProjectLifecycle(
  projectId: string | null | undefined, artefactType: string, api: LifecyclesApi = lifecyclesApi,
): EffectiveLifecycle {
  const [lifecycle, setLifecycle] = useState<ProjectLifecycle | null>(null);

  const load = useCallback(async () => {
    if (!projectId) {
      setLifecycle(null);
      return;
    }
    try {
      const all = await api.project(projectId);
      setLifecycle(all.lifecycles.find((l) => l.artefact_type === artefactType) ?? null);
    } catch {
      setLifecycle(null);
    }
  }, [api, projectId, artefactType]);
  useLoadOnChange(load, [projectId, artefactType]);

  const disabled = lifecycle ? new Set(lifecycle.disabled) : NONE;
  return {
    lifecycle,
    disabled,
    visibleSteps: (steps, current) => steps.filter((s) => s.key === current || !disabled.has(s.key)),
    nextOnPath: (path, current) => path.slice(path.indexOf(current) + 1).find((key) => !disabled.has(key)),
    lastOnPath: (path, key) => path.slice(0, path.indexOf(key) + 1).reverse().find((k) => !disabled.has(k)) ?? key,
    canMove: (from, to, base) => (lifecycle ? (lifecycle.transitions[from] ?? []).includes(to) : base),
  };
}
