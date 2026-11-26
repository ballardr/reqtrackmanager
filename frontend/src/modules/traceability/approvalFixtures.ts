/**
 * Module: modules/traceability/approvalFixtures
 *
 * Fixture data of the approval and lifecycle screens' stories: the roles an organisation offers, and a profile's and a
 * project's approval and lifecycle policy built from them.
 */
import type {
  ApproverRoleOption,
  ProfileApproval,
  ProfileLifecycle,
  ProfileStageWorkflow,
  ProjectApproval,
} from "./types";

export const ROLE_OPTIONS: ApproverRoleOption[] = [
  { kind: "project", key: "project_manager", label: "Project Manager", scope: "project" },
  { kind: "project", key: "project_administrator", label: "Project Administrator", scope: "project" },
  { kind: "module", key: "traceability:governance_manager", label: "Governance Manager", scope: "project" },
  { kind: "custom", key: "role-qa", label: "Quality Lead", scope: "org" },
];

/** A profile's approval policy: the Decision has one added approver, the Requirement none. */
export function profileApproval(overrides: Partial<ProfileApproval> = {}): ProfileApproval {
  return {
    role_options: ROLE_OPTIONS,
    types: [
      { artefact_type: "requirement", label: "Requirement", module_key: "", roles: [] },
      {
        artefact_type: "decision", label: "Decision", module_key: "decisions",
        roles: [{ kind: "custom", key: "role-qa", label: "Quality Lead" }],
      },
    ],
    ...overrides,
  };
}

/** A project's approval policy: its own row for the Decision, the parent's for the Requirement. */
export function projectApproval(overrides: Partial<ProjectApproval> = {}): ProjectApproval {
  return {
    can_manage: true,
    role_options: ROLE_OPTIONS,
    types: [
      {
        artefact_type: "requirement", label: "Requirement", module_key: "", own: null, inherited_from: "Programme Alpha",
        effective: [
          { role: { kind: "project", key: "project_manager", label: "Project Manager" }, sources: ["parent_project", "Regulated work"] },
        ],
      },
      {
        artefact_type: "decision", label: "Decision", module_key: "decisions",
        own: [{ kind: "custom", key: "role-qa", label: "Quality Lead" }], inherited_from: null,
        effective: [{ role: { kind: "custom", key: "role-qa", label: "Quality Lead" }, sources: ["project"] }],
      },
      { artefact_type: "strategy", label: "Strategy", module_key: "context_strategy", own: null, inherited_from: null, effective: [] },
    ],
    ...overrides,
  };
}

/** A profile's lifecycle policy: the Requirement requires Reviewed, the Risk requires nothing. */
export function profileLifecycle(overrides: Partial<ProfileLifecycle> = {}): ProfileLifecycle {
  return {
    skip_forbidden: false,
    types: [
      {
        artefact_type: "requirement", label: "Requirement", module_key: "",
        states: [{ key: "reviewed", label: "Reviewed" }], required: ["reviewed"],
      },
      {
        artefact_type: "risk", label: "Risk", module_key: "risk_management",
        states: [{ key: "assessed", label: "Assessed" }, { key: "treated", label: "Treated" }], required: [],
      },
    ],
    ...overrides,
  };
}

/** A profile's stage workflow policy with two organisation workflows to choose from. */
export function profileStageWorkflow(overrides: Partial<ProfileStageWorkflow> = {}): ProfileStageWorkflow {
  return {
    workflow_id: null, workflow_name: null, mode: "default",
    options: [{ id: "wf-1", name: "Standard delivery" }, { id: "wf-2", name: "Regulated delivery" }],
    ...overrides,
  };
}
