/**
 * Module: testing/approvalSeparationFixtures
 *
 * Builders and a fake `ApprovalSeparationApi` for the approval separation stories and the record pages that read a
 * record's approval status.
 */
import { fn } from "storybook/test";

import type {
  ApprovalSeparationApi, ApprovalStatus, OrgSeparation, ProjectSeparation, ProjectSeparations,
} from "../api/approvalSeparation";

/** One type's rule as a project sees it: the Change request by default, with the default choice. */
export function buildProjectSeparation(overrides: Partial<ProjectSeparation> = {}): ProjectSeparation {
  return {
    artefact_type: "change_request", label: "Change request", module_key: "", module_name: "", own: null, chosen: false,
    source: "default", required: false, exempt: false, separate: false, ...overrides,
  };
}

export function buildProjectSeparations(types: ProjectSeparation[], overrides: Partial<ProjectSeparations> = {}): ProjectSeparations {
  return { can_manage: true, has_parent: false, types, ...overrides };
}

export function buildOrgSeparation(overrides: Partial<OrgSeparation> = {}): OrgSeparation {
  return {
    artefact_type: "change_request", label: "Change request", module_key: "", module_name: "", required: false,
    exemptions: [], ...overrides,
  };
}

/** A record's approval status: not self-approved and not blocked, unless overridden. */
export function buildApprovalStatus(overrides: Partial<ApprovalStatus> = {}): ApprovalStatus {
  return { self_approved: false, approved_by_name: null, approved_at: null, needs_other_approver: false, ...overrides };
}

/** A fake API whose methods are spies; `project`, `organization` and `status` are the data every read returns. */
export function buildApprovalSeparationApi(
  project: ProjectSeparations = buildProjectSeparations([
    buildProjectSeparation(), buildProjectSeparation({ artefact_type: "decision", label: "Decision", module_key: "decisions", module_name: "Decision Management" }),
  ]),
  organization: OrgSeparation[] = [buildOrgSeparation()],
  status: ApprovalStatus = buildApprovalStatus(),
): ApprovalSeparationApi {
  return {
    project: fn(async () => project),
    setProject: fn(async (_projectId: string, artefactType: string, separate: boolean | null) => ({
      ...project,
      types: project.types.map((t) => (t.artefact_type === artefactType
        ? { ...t, own: separate, chosen: separate ?? false, separate: separate ?? false, source: separate === null ? "default" as const : "project" as const }
        : t)),
    })),
    organization: fn(async () => organization),
    setRequired: fn(async (_organizationId: string, artefactType: string, required: boolean) =>
      organization.map((o) => (o.artefact_type === artefactType ? { ...o, required } : o))),
    addExemption: fn(async (_organizationId: string, artefactType: string, projectId: string, includeChildren: boolean) =>
      organization.map((o) => (o.artefact_type === artefactType
        ? { ...o, exemptions: [...o.exemptions, { project_id: projectId, project_name: "Solo project", project_code: "SOLO", include_children: includeChildren }] }
        : o))),
    removeExemption: fn(async (_organizationId: string, artefactType: string, projectId: string) =>
      organization.map((o) => (o.artefact_type === artefactType
        ? { ...o, exemptions: o.exemptions.filter((e) => e.project_id !== projectId) } : o))),
    status: fn(async () => status),
  };
}
