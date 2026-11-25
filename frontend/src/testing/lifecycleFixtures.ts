/**
 * Module: testing/lifecycleFixtures
 *
 * Builders and a fake `LifecyclesApi` for the lifecycle settings stories and the record pages that read the effective
 * lifecycle. The pain point type has Triaged as its one optional state; the decision type has Proposed and Under review.
 */
import { fn } from "storybook/test";

import type {
  LifecyclesApi, LifecycleState, OrgLifecycle, OrgSkip, ProjectLifecycle, ProjectLifecycles, ProjectSkip,
} from "../api/lifecycles";

const state = (key: string, label: string, optional = false, gated = false): LifecycleState => ({ key, label, optional, gated });

/** The Pain Point lifecycle; `disabled` are the states turned off and `required` those the organisation requires. */
export function buildPainPointLifecycle(overrides: Partial<ProjectLifecycle> = {}): ProjectLifecycle {
  const disabled = overrides.disabled ?? [];
  const transitions: Record<string, string[]> = disabled.includes("triaged")
    ? { submitted: ["accepted", "rejected", "duplicate"], triaged: ["accepted", "rejected", "duplicate"], accepted: ["addressed"], addressed: ["closed"] }
    : { submitted: ["triaged"], triaged: ["accepted", "rejected", "duplicate"], accepted: ["addressed"], addressed: ["closed"] };
  return {
    artefact_type: "pain_point", label: "Pain Point", module_key: "context_strategy", module_name: "Context & Strategy",
    path: [
      state("submitted", "Submitted"), state("triaged", "Triaged", true), state("accepted", "Accepted"),
      state("addressed", "Addressed"), state("closed", "Closed"),
    ],
    off_path: [state("rejected", "Rejected"), state("duplicate", "Duplicate")],
    own_disabled: disabled.length > 0 ? disabled : null, disabled, required: [], exempt: false,
    source: disabled.length > 0 ? "project" : "default", transitions, skip_transitions: {}, ...overrides,
  };
}

/** The Pain Point skip moves with every step on: from Submitted to Accepted, Addressed or Closed, and so on. */
export const PAIN_POINT_SKIPS: ProjectLifecycle["skip_transitions"] = {
  submitted: { accepted: ["triaged"], addressed: ["triaged", "accepted"], closed: ["triaged", "accepted", "addressed"] },
  triaged: { addressed: ["accepted"], closed: ["accepted", "addressed"] },
  accepted: { closed: ["addressed"] },
};

/** The Decision skip moves with every step on: Draft to Under review or to Approved (the gated step may be the target). */
export const DECISION_SKIPS: ProjectLifecycle["skip_transitions"] = {
  draft: { under_review: ["proposed"], approved: ["proposed", "under_review"] },
  proposed: { approved: ["under_review"] },
};

/** The Decision lifecycle with Proposed and Under review optional and Approved gated. */
export function buildDecisionLifecycle(overrides: Partial<ProjectLifecycle> = {}): ProjectLifecycle {
  return {
    artefact_type: "decision", label: "Decision", module_key: "decisions", module_name: "Decision Management",
    path: [state("draft", "Draft"), state("proposed", "Proposed", true), state("under_review", "Under review", true), state("approved", "Approved", false, true)],
    off_path: [state("rejected", "Rejected"), state("superseded", "Superseded")],
    own_disabled: null, disabled: [], required: [], exempt: false, source: "default",
    transitions: { draft: ["proposed"], proposed: ["under_review", "rejected"], under_review: ["approved", "rejected"], approved: ["superseded"] },
    skip_transitions: {},
    ...overrides,
  };
}

/** Skipping steps as a project sees it: off by default; pass `{ chosen: true, own: true, allowed: true }` to allow it. */
export function buildProjectSkip(overrides: Partial<ProjectSkip> = {}): ProjectSkip {
  return { allowed: false, own: null, chosen: false, source: "default", forbidden: false, exempt: false, ...overrides };
}

export function buildProjectLifecycles(lifecycles: ProjectLifecycle[], overrides: Partial<ProjectLifecycles> = {}): ProjectLifecycles {
  return { can_manage: true, has_parent: false, skip: buildProjectSkip(), lifecycles, ...overrides };
}

export function buildOrgSkip(overrides: Partial<OrgSkip> = {}): OrgSkip {
  return { forbidden: false, exemptions: [], ...overrides };
}

export function buildOrgLifecycle(overrides: Partial<OrgLifecycle> = {}): OrgLifecycle {
  return {
    artefact_type: "pain_point", label: "Pain Point", module_key: "context_strategy", module_name: "Context & Strategy",
    states: [state("triaged", "Triaged", true)], required: [], exemptions: [], ...overrides,
  };
}

/** A fake API whose methods are spies; `project` and `organization` are the data every read returns. */
export function buildLifecyclesApi(
  project: ProjectLifecycles = buildProjectLifecycles([buildPainPointLifecycle(), buildDecisionLifecycle()]),
  organization: OrgLifecycle[] = [buildOrgLifecycle()],
  organizationSkip: OrgSkip = buildOrgSkip(),
): LifecyclesApi {
  return {
    project: fn(async () => project),
    setProject: fn(async (_projectId: string, artefactType: string, disabled: string[] | null) => ({
      ...project,
      lifecycles: project.lifecycles.map((l) => (l.artefact_type === artefactType
        ? { ...l, own_disabled: disabled, disabled: disabled ?? [], source: disabled === null ? "default" as const : "project" as const }
        : l)),
    })),
    setProjectSkip: fn(async (_projectId: string, allowed: boolean | null) => ({
      ...project,
      skip: {
        ...project.skip, own: allowed, chosen: allowed ?? false, source: allowed === null ? "default" as const : "project" as const,
        allowed: (allowed ?? false) && !project.skip.forbidden,
      },
    })),
    organization: fn(async () => organization),
    organizationSkip: fn(async () => organizationSkip),
    setSkipForbidden: fn(async (_organizationId: string, forbidden: boolean) => ({ ...organizationSkip, forbidden })),
    addSkipExemption: fn(async (_organizationId: string, projectId: string, includeChildren: boolean) => ({
      ...organizationSkip,
      exemptions: [...organizationSkip.exemptions, { project_id: projectId, project_name: "Solo project", project_code: "SOLO", include_children: includeChildren }],
    })),
    removeSkipExemption: fn(async (_organizationId: string, projectId: string) => ({
      ...organizationSkip, exemptions: organizationSkip.exemptions.filter((e) => e.project_id !== projectId),
    })),
    setRequired: fn(async (_organizationId: string, artefactType: string, required: string[]) =>
      organization.map((o) => (o.artefact_type === artefactType ? { ...o, required } : o))),
    addExemption: fn(async (_organizationId: string, artefactType: string, projectId: string, includeChildren: boolean) =>
      organization.map((o) => (o.artefact_type === artefactType
        ? { ...o, exemptions: [...o.exemptions, { project_id: projectId, project_name: "Solo project", project_code: "SOLO", include_children: includeChildren }] }
        : o))),
    removeExemption: fn(async (_organizationId: string, artefactType: string, projectId: string) =>
      organization.map((o) => (o.artefact_type === artefactType
        ? { ...o, exemptions: o.exemptions.filter((e) => e.project_id !== projectId) } : o))),
  };
}
