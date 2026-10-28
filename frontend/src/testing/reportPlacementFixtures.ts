/**
 * Module: testing/reportPlacementFixtures
 *
 * Storybook-only builders for report placements: the rows the placement panel lists and a stateful fake
 * `ReportPlacementApi` that keeps the overrides a story sets, as the server would resolve them for one scope.
 */
import { fn } from "storybook/test";

import type { PlacementChange, ReportPlacement, ReportPlacementApi } from "../api/reportPlacements";

/** A module report with its default folder and no override. */
export function buildPlacement(overrides: Partial<ReportPlacement> = {}): ReportPlacement {
  return {
    report_key: "report:decisions.d1", title: "Decision register", description: "Every Decision.", kind: "report",
    group: "Decision Management", default_folder: "Decision Management", folder: "Decision Management", folder_from: null,
    own_folder: null, hidden: false, hidden_from: null, own_hidden: null, can_hide: true, ...overrides,
  };
}

/** The rows a story starts from: module reports, a custom layout, a sheet and a pack. */
export function buildPlacements(): ReportPlacement[] {
  return [
    buildPlacement(),
    buildPlacement({ report_key: "report:decisions.d2", title: "Approval ageing", description: "" }),
    buildPlacement({
      report_key: "report:risk_management.r1", title: "Risk register", description: "Every Risk.", group: "Risk Management",
      default_folder: "Risk Management", folder: "Risk Management",
    }),
    buildPlacement({
      report_key: "layout:1", title: "Handover document", description: "", group: "Custom reports", default_folder: "Custom reports",
      folder: "Custom reports", can_hide: false,
    }),
    buildPlacement({
      report_key: "layout:2", title: "Handover rows", description: "", kind: "sheet", group: "Custom reports",
      default_folder: "Custom reports", folder: "Custom reports", can_hide: false,
    }),
    buildPlacement({
      report_key: "pack:1", title: "Programme handover", description: "", kind: "pack", group: "Report packs",
      default_folder: "Report packs", folder: "Report packs", can_hide: false,
    }),
  ];
}

/**
 * A fake API over `rows` for an organisation or a project; `set` applies the change as the server would for this scope
 * (a field left out is unchanged, `null` clears this scope's override) and answers the refreshed list.
 */
export function buildPlacementApi(
  rows: ReportPlacement[] = buildPlacements(), kind: "project" | "organization" = "project",
): ReportPlacementApi {
  const store = rows.map((row) => ({ ...row }));
  const own: "project" | "organization" = kind;
  return {
    scope: { kind, id: kind === "project" ? "project-1" : "org-1" },
    list: fn(async () => store.map((row) => ({ ...row }))),
    set: fn(async (change: PlacementChange) => {
      const row = store.find((r) => r.report_key === change.report_key);
      if (!row) throw new Error("There is no such report here.");
      if ("folder" in change) {
        row.own_folder = change.folder ?? null;
        row.folder = row.own_folder ?? row.default_folder;
        row.folder_from = row.own_folder === null ? null : own;
      }
      if ("hidden" in change) {
        row.own_hidden = change.hidden ?? null;
        row.hidden = row.own_hidden === true;
        row.hidden_from = row.own_hidden === null ? null : own;
      }
      return store.map((r) => ({ ...r }));
    }),
    resolved: fn(async () => []),
  };
}
