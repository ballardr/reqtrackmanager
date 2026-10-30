/**
 * Module: testing/reportCopyFixtures
 *
 * Storybook-only fake `ReportCopyApi`: answers a copy request the way the server would for a handful of known reports, so
 * the dialog's preview, outcomes and warnings can be driven without a server.
 */
import { fn } from "storybook/test";

import type { CopyItemResult, CopyKind, CopyRequest, CopyResult, CopyTarget, ReportCopyApi } from "../api/reportCopy";

/** Two projects a person could copy into. */
export function buildCopyTargets(): CopyTarget[] {
  return [
    { id: "project-2", name: "Apollo", parent_project_id: null },
    { id: "project-3", name: "Apollo phase 2", parent_project_id: "project-2" },
  ];
}

/**
 * @param names The name of each layout, pack, folder or placement by its id (an unknown id uses the id).
 * @param renamed Ids whose name the target already uses, so they copy under "<name> (copy)".
 * @param warnings Warnings by id.
 * @param targets The projects on offer; `[]` for none.
 */
export function buildCopyApi(
  { names = {}, renamed = [], warnings = {}, targets = buildCopyTargets() }:
    { names?: Record<string, string>; renamed?: string[]; warnings?: Record<string, string[]>; targets?: CopyTarget[] } = {},
): ReportCopyApi {
  const item = (kind: CopyKind, id: string, request: CopyRequest): CopyItemResult => {
    const name = names[id] ?? id;
    const rename = renamed.includes(id) && request.on_conflict === "rename";
    const skip = renamed.includes(id) && request.on_conflict === "skip";
    return {
      kind, source_id: id, name, origin: "project", action: skip ? "skip" : rename ? "rename" : "create",
      new_name: rename ? `${name} (copy)` : name, warnings: warnings[id] ?? [], new_id: request.dry_run ? null : `new-${id}`,
    };
  };
  return {
    targets: fn(async () => targets),
    copy: fn(async (targetProjectId: string, request: CopyRequest): Promise<CopyResult> => ({
      dry_run: request.dry_run,
      target_project_id: targetProjectId,
      items: [
        ...request.layout_ids.map((id) => item("layout", id, request)),
        ...request.pack_ids.map((id) => item("pack", id, request)),
        ...request.folders.map((id) => item("folder", id, request)),
        ...request.placement_keys.map((id) => item("placement", id, request)),
      ],
      warnings: [],
      favourites_carried: request.dry_run ? 0 : 1,
    })),
  };
}
