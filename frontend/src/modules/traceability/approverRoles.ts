/**
 * Module: traceability/approverRoles
 *
 * Labels and small helpers for the roles an approval policy names, shared by the profile and project approval screens
 * and the role field. `ApproverRole` and its option types are in `types.ts`.
 *
 * Responsibilities: label each role kind and scope, give a role one string identity (`kind` and `key`), and turn the
 * source of an effective role into words.
 */
import type { ApproverRole, ApproverRoleKind, ApproverRoleOption } from "./types";

/** The heading of each kind of role in the role list. */
export const APPROVER_ROLE_KIND_LABEL: Record<ApproverRoleKind, string> = {
  project: "Project roles",
  module: "Module roles",
  custom: "Custom roles",
};

/** The order the kinds are listed in. */
export const APPROVER_ROLE_KIND_ORDER: readonly ApproverRoleKind[] = ["project", "module", "custom"];

/** Where a role is granted. */
export const APPROVER_ROLE_SCOPE_LABEL: Record<ApproverRoleOption["scope"], string> = {
  org: "Organisation role",
  project: "Project role",
};

/**
 * @param role A role.
 * @returns A string that is the same for the same `kind` and `key` and differs otherwise.
 */
export function roleId(role: ApproverRole): string {
  return `${role.kind}:${role.key}`;
}

/**
 * @param source One entry of an effective role's `sources`: `project`, `parent_project` or a profile's name.
 * @returns The source in words.
 */
export function sourceLabel(source: string): string {
  if (source === "project") return "This project";
  if (source === "parent_project") return "Parent project";
  return source;
}
