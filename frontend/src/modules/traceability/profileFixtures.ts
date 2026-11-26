/**
 * Module: modules/traceability/profileFixtures
 *
 * Profile fixtures shared by the stories of the profile list, the profile page, its Overview tab and the target and
 * exemption fields: an organisation, its projects and profiles of each mode, and a router for the calls those screens make.
 */
import type { ProfileDetail } from "./types";

export const ORG_ID = "org-1";

/** The organisation's projects as the project list returns them. */
export const ORG_PROJECTS = [
  { id: "proj-1", name: "Harbour crossing", code: "HBR" },
  { id: "proj-2", name: "Signalling upgrade", code: "SIG" },
  { id: "proj-3", name: "Depot refit", code: "DEP" },
];

/** The sub-components of the module, all on for the organisation. */
export const SUB_COMPONENTS = ["lifecycle_policies", "approval_policies", "review_policies", "baseline_policies", "governance_health"].map((key) => ({
  module_key: "traceability", subcomponent_key: key, name: key, default_enabled: true, enabled: true, default_project_enabled: true,
  has_org_override: false, blocked_by: [],
}));

const STAMP = "2026-11-26T09:00:00Z";

/** An Enforced profile reaching two projects, with one exemption and the effect on each project it reaches. */
export const ENFORCED_PROFILE: ProfileDetail = {
  id: "prof-1", name: "Safety critical", description: "Every project that ships to customers.", mode: "enforced",
  target_kind: "selected_projects",
  targets: [
    { project_id: "proj-1", project_name: "HBR Harbour crossing", include_children: true },
    { project_id: "proj-2", project_name: "SIG Signalling upgrade", include_children: false },
  ],
  exemptions: [{ project_id: "proj-2", project_name: "SIG Signalling upgrade", include_children: false, reason: "Superseded by the programme profile." }],
  contributions: [{ key: "traceability:approval", name: "Approval policy", count: 2 }, { key: "traceability:review", name: "Review policy", count: 1 }],
  created_at: STAMP, updated_at: STAMP,
  projects: [
    { project_id: "proj-1", project_name: "HBR Harbour crossing", outcome: "enforced", applies: true, choice: null },
    { project_id: "proj-2", project_name: "SIG Signalling upgrade", outcome: "exempt", applies: false, choice: null },
  ],
};

/** A Default profile reaching every project, one of which opted out. */
export const DEFAULT_PROFILE: ProfileDetail = {
  id: "prof-2", name: "Standard review", description: "Quarterly review of every record.", mode: "default", target_kind: "all_projects",
  targets: [], exemptions: [], contributions: [], created_at: STAMP, updated_at: STAMP,
  projects: [
    { project_id: "proj-1", project_name: "HBR Harbour crossing", outcome: "default", applies: true, choice: null },
    { project_id: "proj-3", project_name: "DEP Depot refit", outcome: "opted_out", applies: false, choice: false },
  ],
};

/** An Opt-in profile reaching every project, one of which opted in. */
export const OPT_IN_PROFILE: ProfileDetail = {
  id: "prof-3", name: "Audit ready", description: "", mode: "opt_in", target_kind: "all_projects", targets: [], exemptions: [],
  contributions: [{ key: "traceability:baseline", name: "Baseline policy", count: 1 }], created_at: STAMP, updated_at: STAMP,
  projects: [{ project_id: "proj-1", project_name: "HBR Harbour crossing", outcome: "opted_in", applies: true, choice: true }],
};

/**
 * @param path A request path.
 * @param detail The profile the page opens.
 * @returns The response of the calls the profile screens make that no story overrides, or `undefined` for another path.
 */
export function profileScreenResponse(path: string, detail: ProfileDetail): unknown {
  if (path.startsWith("/api/v1/projects?organization_id=")) return ORG_PROJECTS;
  if (path.endsWith("/modules/traceability/subcomponents")) return SUB_COMPONENTS;
  if (path.endsWith(`/profiles/${detail.id}`)) return detail;
  return undefined;
}
