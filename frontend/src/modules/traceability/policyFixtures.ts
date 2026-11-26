/**
 * Module: modules/traceability/policyFixtures
 *
 * Shared Storybook fixtures for the review and baseline policy screens: record types, principals, organisation users,
 * review and baseline responses of a profile and of a project, and a network mock that answers `api.get` by path.
 * Imported by stories only.
 */
import { spyOn } from "storybook/test";

import { api } from "../../api/client";
import type { OrgUser, Principal } from "../../api/types";
import type {
  BaselineCheckOption, BaselineFieldOption, BaselinePreview, BaselineSettings, BaselineType, ProfileBaseline, ProfileReview,
  ProjectBaseline, ProjectReview,
} from "./types";

export const ORG_ID = "org-1";
export const PROFILE_ID = "profile-1";
export const PROJECT_ID = "project-1";

export const DANA: Principal = { type: "user", id: "user-1", label: "Dana Whitfield", member_count: null, exists: true };
export const PMO: Principal = { type: "org_group", id: "group-1", label: "Programme Office", member_count: 4, exists: true };

export const ORG_USERS = [
  { user_id: "user-1", email: "dana@example.com", display_name: "Dana Whitfield", is_active: true, is_archived: false, roles: [] },
] as unknown as OrgUser[];

/** `GET /orgs/{id}/users`, as the owner pickers read it. */
export const ORG_USERS_URL = `/api/v1/orgs/${ORG_ID}/users`;

export const profileReviewUrl = `/api/v1/orgs/${ORG_ID}/modules/traceability/profiles/${PROFILE_ID}/review`;
export const profileBaselineUrl = `/api/v1/orgs/${ORG_ID}/modules/traceability/profiles/${PROFILE_ID}/baseline`;
export const projectReviewUrl = `/api/v1/projects/${PROJECT_ID}/modules/traceability/review-policies`;
export const projectBaselineUrl = `/api/v1/projects/${PROJECT_ID}/modules/traceability/baseline-policy`;

export function buildProfileReview(): ProfileReview {
  return {
    types: [
      { artefact_type: "requirement", label: "Requirement", module_key: "", settings: { interval_days: 90, lead_days: 14, default_owner: DANA } },
      { artefact_type: "risk", label: "Risk", module_key: "risk_management", settings: { interval_days: null, lead_days: null, default_owner: null } },
    ],
  };
}

export function buildProjectReview(canManage = true): ProjectReview {
  return {
    can_manage: canManage,
    types: [
      {
        artefact_type: "requirement", label: "Requirement", module_key: "",
        own: { interval_days: 60, lead_days: 7, default_owner: PMO }, inherited_from: null,
        effective: {
          interval_days: 60, interval_source: "project", lead_days: 14, lead_source: "Assurance profile",
          default_owner: PMO, owner_source: "project",
        },
      },
      {
        artefact_type: "risk", label: "Risk", module_key: "risk_management", own: null, inherited_from: "Programme Atlas",
        effective: {
          interval_days: 30, interval_source: "parent_project", lead_days: null, lead_source: null, default_owner: null, owner_source: null,
        },
      },
    ],
  };
}

export const BASELINE_CHECKS: BaselineCheckOption[] = [
  { key: "traceability:required_fields", name: "Required fields", module_key: "traceability", artefact_types: [] },
  { key: "traceability:required_approvals", name: "Required approvals", module_key: "traceability", artefact_types: ["requirement"] },
];
export const BASELINE_TYPES: BaselineType[] = [
  { artefact_type: "requirement", label: "Requirement", module_key: "" },
  { artefact_type: "risk", label: "Risk", module_key: "risk_management" },
];
export const FIELD_OPTIONS: Record<string, BaselineFieldOption[]> = {
  requirement: [{ key: "reasoning", label: "Reasoning" }, { key: "owner", label: "Owner" }],
  risk: [{ key: "statement", label: "Risk statement" }],
};

export const EMPTY_BASELINE: BaselineSettings = {
  applies_to_stage: true, applies_to_manual: false, notify_managers: true, checks: [], required_fields: [],
};
export const FILLED_BASELINE: BaselineSettings = {
  applies_to_stage: true, applies_to_manual: true, notify_managers: true,
  checks: ["traceability:required_fields"], required_fields: [{ artefact_type: "requirement", field_key: "reasoning" }],
};

export function buildProfileBaseline(settings: BaselineSettings = FILLED_BASELINE): ProfileBaseline {
  return { settings, check_options: BASELINE_CHECKS, types: BASELINE_TYPES };
}

export function buildProjectBaseline(canManage = true, own: BaselineSettings | null = FILLED_BASELINE): ProjectBaseline {
  return {
    can_manage: canManage, own, inherited_from: own ? null : "Programme Atlas",
    checks: [
      { key: "traceability:required_fields", name: "Required fields", available: true, stage: true, manual: true, sources: ["Assurance profile", "project"] },
      { key: "compliance:evidence", name: null, available: false, stage: true, manual: false, sources: ["parent_project"] },
    ],
    required_fields: [
      { artefact_type: "requirement", field_key: "reasoning", field_label: "Reasoning", stage: true, manual: true, sources: ["project"] },
      { artefact_type: "risk", field_key: "custom_gone", field_label: null, stage: true, manual: false, sources: ["Assurance profile"] },
    ],
    notify_managers: true, check_options: BASELINE_CHECKS, types: BASELINE_TYPES, field_options: FIELD_OPTIONS,
  };
}

export const PREVIEW_WITH_FAILURES: BaselinePreview = {
  kind: "stage", checks: [{ key: "traceability:required_fields", name: "Required fields" }],
  failures: [
    { check_key: "traceability:required_fields", check_name: "Required fields", artefact_type: "requirement", artefact_id: "r1", code: "REQ-004", message: "Reasoning is empty." },
    { check_key: "traceability:required_fields", check_name: "Required fields", artefact_type: "requirement", artefact_id: "r2", code: "REQ-009", message: "Reasoning is empty." },
  ],
};
export const PREVIEW_CLEAR: BaselinePreview = { kind: "stage", checks: [{ key: "traceability:required_fields", name: "Required fields" }], failures: [] };

/**
 * Answers `api.get` by path prefix (the longest matching prefix wins), so a story names only the reads it needs; any other
 * read rejects, which the components treat as a failed load.
 *
 * @param answers `{path prefix: response}`; a function is called with the path.
 */
export function mockGets(answers: Record<string, unknown | ((path: string) => unknown)>): void {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    const match = Object.keys(answers).filter((prefix) => path.startsWith(prefix)).sort((a, b) => b.length - a.length)[0];
    if (match === undefined) throw new Error(`unmocked GET: ${path}`);
    const answer = answers[match];
    return typeof answer === "function" ? (answer as (p: string) => unknown)(path) : answer;
  });
}
