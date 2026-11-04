/**
 * Module: testing/reportDuplicateFixtures
 *
 * Storybook-only fake `ReportDuplicateApi`: answers a duplicate request the way the server would (a suggested "(copy)" name,
 * a taken name, a shadowed name, pictures that block a copy up, a refusal), so the dialog can be driven without a server.
 */
import { fn } from "storybook/test";

import { ApiError } from "../api/client";
import type { DuplicateRequest, DuplicateResult, ReportDuplicateApi, ReportStarter } from "../api/reportDuplicate";
import type { LayoutScope } from "../api/reportLayouts";

export const STARTERS: ReportStarter[] = [
  { key: "business-requirements-document", name: "Business Requirements Document", description: "Why the work is needed and what the business expects.", orientation: "portrait" },
  { key: "review-package", name: "Review Package", description: "What a reviewer needs to sign off.", orientation: "portrait" },
];

/**
 * @param scope The scope the API is bound to (a project by default).
 * @param sourceName The name of the layout or pack being copied (a starter uses its own).
 * @param taken Lower-cased names the destination already owns.
 * @param shadows Lower-cased names the project inherits.
 * @param blockedUp Filenames of project pictures that block a copy up to the organisation.
 * @param refuseUp Whether a copy up is refused for lack of the organisation's right.
 */
export function buildDuplicateApi(
  { scope = { kind: "project", id: "project-1" }, sourceName = "Handover document", taken = [], shadows = [], blockedUp = [], refuseUp = false }:
    { scope?: LayoutScope; sourceName?: string; taken?: string[]; shadows?: string[]; blockedUp?: string[]; refuseUp?: boolean } = {},
): ReportDuplicateApi {
  return {
    scope,
    starters: fn(async () => STARTERS),
    duplicate: fn(async (request: DuplicateRequest): Promise<DuplicateResult> => {
      if (request.target === "organization" && refuseUp) throw new ApiError(403, "Insufficient permissions in the organisation.");
      const source = request.kind === "starter" ? (STARTERS.find((s) => s.key === request.starter_key)?.name ?? "") : sourceName;
      const suggested = request.kind === "starter" && !taken.includes(source.toLowerCase()) ? source : `${source} (copy)`;
      const name = request.name ?? suggested;
      const blocked = request.target === "organization" ? blockedUp : [];
      return {
        dry_run: request.dry_run, kind: request.kind, source_name: source, origin: request.kind === "starter" ? "starter" : "organization",
        name, suggested_name: suggested, name_taken: taken.includes(name.toLowerCase()), shadows: shadows.includes(name.toLowerCase()),
        folder: "", blocked_images: blocked,
        warnings: shadows.includes(name.toLowerCase()) ? ["The copy will shadow a report of the same name that this project inherits."] : [],
        new_id: request.dry_run ? null : "new-1", target: request.target, organization_id: "org-1",
      };
    }),
  };
}
