/**
 * Module: testing/lifecycleFixtures
 *
 * Builders and a fake `LifecyclesApi` for the lifecycle settings stories and the record pages that read the effective
 * lifecycle. The pain point type has Triaged as its one optional state; the decision type has Proposed and Under review.
 */
import { fn } from "storybook/test";

import type { LifecyclesApi, LifecycleState, OrgLifecycle, ProjectLifecycle, ProjectLifecycles } from "../api/lifecycles";

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
    source: disabled.length > 0 ? "project" : "default", transitions, ...overrides,
  };
}

/** The Decision lifecycle with Proposed and Under review optional and Approved gated. */
export function buildDecisionLifecycle(overrides: Partial<ProjectLifecycle> = {}): ProjectLifecycle {
  return {
    artefact_type: "decision", label: "Decision", module_key: "decisions", module_name: "Decision Management",
    path: [state("draft", "Draft"), state("proposed", "Proposed", true), state("under_review", "Under review", true), state("approved", "Approved", false, true)],
    off_path: [state("rejected", "Rejected"), state("superseded", "Superseded")],
    own_disabled: null, disabled: [], required: [], exempt: false, source: "default",
    transitions: { draft: ["proposed"], proposed: ["under_review", "rejected"], under_review: ["approved", "rejected"], approved: ["superseded"] },
    ...overrides,
  };
}

export function buildProjectLifecycles(lifecycles: ProjectLifecycle[], overrides: Partial<ProjectLifecycles> = {}): ProjectLifecycles {
  return { can_manage: true, has_parent: false, lifecycles, ...overrides };
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
): LifecyclesApi {
  return {
    project: fn(async () => project),
    setProject: fn(async (_projectId: string, artefactType: string, disabled: string[] | null) => ({
      ...project,
      lifecycles: project.lifecycles.map((l) => (l.artefact_type === artefactType
        ? { ...l, own_disabled: disabled, disabled: disabled ?? [], source: disabled === null ? "default" as const : "project" as const }
        : l)),
    })),
    organization: fn(async () => organization),
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
