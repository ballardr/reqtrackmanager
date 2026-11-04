/**
 * Module: testing/reportFileFixtures
 *
 * Storybook-only fake `ReportFileApi`: answers an import the way the server would for a few named layouts and packs,
 * so the export and import dialogs can be driven without a server.
 */
import { fn } from "storybook/test";

import type { FileConflict, FileExportRequest, FileImportResult, FileItemResult, ReportFileApi } from "../api/reportFile";

/** What the fake file "contains" and which names the target already uses. */
export interface FakeFile {
  layouts?: string[];
  packs?: string[];
  taken?: string[];
  broken?: string[];
  warnings?: Record<string, string[]>;
  pictures?: number;
  fail?: string;
  scope?: ReportFileApi["scope"];
}

export function buildFileApi(
  { layouts = ["Handover document", "Monthly status"], packs = ["Board pack"], taken = [], broken = [], warnings = {}, pictures = 0, fail, scope }: FakeFile = {},
): ReportFileApi {
  const item = (kind: "layout" | "pack", name: string, onConflict: FileConflict, dryRun: boolean): FileItemResult => {
    const left = broken.includes(name);
    const clash = taken.includes(name);
    const action = left ? "left_out" : clash ? (onConflict === "skip" ? "skip" : "rename") : "create";
    return {
      kind, name, new_name: action === "rename" ? `${name} (copy)` : name, action, versions: 1,
      warnings: left ? ["No version is valid here: nodes[0]: unknown block type."] : (warnings[name] ?? []),
      new_id: dryRun || left || action === "skip" ? null : `new-${name}`,
    };
  };
  return {
    scope: scope ?? { kind: "project", id: "project-1" },
    exportFile: fn(async (_request: FileExportRequest) => new Blob(["zip"], { type: "application/zip" })),
    importFile: fn(async (_file: File, { onConflict, dryRun }: { onConflict: FileConflict; dryRun: boolean }): Promise<FileImportResult> => {
      if (fail) throw new Error(fail);
      return {
        dry_run: dryRun, pictures,
        items: [...layouts.map((n) => item("layout", n, onConflict, dryRun)), ...packs.map((n) => item("pack", n, onConflict, dryRun))],
        warnings: pictures > 0 ? [`${pictures} picture(s) will be added to this project's library.`] : [],
      };
    }),
  };
}
