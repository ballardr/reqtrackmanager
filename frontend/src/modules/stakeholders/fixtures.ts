/**
 * Module: modules/stakeholders/fixtures
 *
 * Shared Storybook fixtures for the stakeholders module's stories — `Persona`,
 * `Stakeholder`, `Need`, `Engagement` and finding builders so every story constructs the same complete wire
 * shape, and the `stakeholder` scoring scheme the Stakeholder form reads.
 */
import type { ScoringScheme } from "../../api/scoring";
import type { Engagement, Need, Persona, ResearchFinding, Stakeholder, StakeholderGroup } from "./types";

/** A complete project-scoped, active `Persona` with `overrides` applied. */
export function buildPersona(overrides: Partial<Persona> = {}): Persona {
  return {
    id: "persona-1", scope: "project", organization_id: null, project_id: "project-1", creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null, name: "Field Technician",
    description: "Inspects equipment on site.", persona_type_id: "type-primary", persona_type_name: "Primary",
    role_title: "Senior technician", goals: "Finish inspections without rework.", needs: "Offline access.",
    behaviours: "Works in short bursts between sites.", context_environment: "Outdoors, gloves on.",
    skills_proficiency: "Expert with the equipment.", frequency_of_use: "Daily", constraints: "No reliable network.",
    weight: 2, status: "active", owner: null, champion: null, version_number: 1,
    effective_weight: 2, weight_override: null, weight_source: "persona",
    project_hidden: null, hidden_override: null, hidden_source: null,
    created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

/** A complete project-scoped, active `Stakeholder` with `overrides` applied. */
export function buildStakeholder(overrides: Partial<Stakeholder> = {}): Stakeholder {
  return {
    id: "stakeholder-1", scope: "project", organization_id: null, project_id: "project-1", creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null, name: "Pat Regulator",
    description: "Audits safety compliance.", stakeholder_type_id: "stype-regulator", stakeholder_type_name: "Regulator",
    role: "Compliance auditor", organisation_group: "Safety Authority", interests: "Evidence of compliance.",
    responsibilities: "Annual audit.", goals_needs: "Traceable records.", priorities: "Safety first.",
    constraints: "Only available in Q4.", workflows_scenarios: "On-site audit.",
    contact_info: "pat@authority.example.com", target_cadence: "quarterly", availability_constraints: "Prefers email.",
    influence_level_id: "infl-high", interest_level_id: "int-medium", status: "active", owner: null, user_id: null,
    version_number: 1, created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    project_hidden: null, hidden_override: null, hidden_source: null, groups: [], last_engaged: null,
    ...overrides,
  };
}

/** A complete org-scoped `StakeholderGroup` with `overrides` applied. */
export function buildStakeholderGroup(overrides: Partial<StakeholderGroup> = {}): StakeholderGroup {
  return {
    id: "group-1", scope: "organization", organization_id: "org-1", project_id: null, parent_group_id: null,
    name: "Client", description: "", exclusive_children: false, sort_order: 0, member_count: 0, child_count: 0,
    ...overrides,
  };
}

/** The org's `stakeholder` scoring scheme (Influence × Interest, default Low/Medium/High levels). */
export function buildStakeholderScheme(): ScoringScheme {
  const levels = (prefix: string) => [
    { id: `${prefix}-low`, name: "Low", description: "Little of either.", weight: 1 },
    { id: `${prefix}-medium`, name: "Medium", description: null, weight: 2 },
    { id: `${prefix}-high`, name: "High", description: "A great deal.", weight: 3 },
  ];
  return {
    key: "stakeholder", label: "Stakeholder scoring", module_key: "stakeholders",
    axes: [
      { key: "influence", label: "Influence", description: null, levels: levels("infl") },
      { key: "interest", label: "Interest", description: null, levels: levels("int") },
    ],
    models: [{
      key: "influence_x_interest", label: "Influence × Interest", axis_keys: ["influence", "interest"],
      bands: [{ label: "Low", min_score: 0, tone: "muted" }], bands_source: "system",
      cell_ratings: [], cell_ratings_source: "none",
    }],
    system_default_model_key: "influence_x_interest", default_model_key: "influence_x_interest",
    default_model_source: "system",
  };
}

/** A complete, active `Need` of project-1 with `overrides` applied. */
export function buildNeed(overrides: Partial<Need> = {}): Need {
  return {
    id: "need-1", project_id: "project-1", creator_id: "user-1", is_archived: false, archived_at: null,
    archived_by: null, name: "Diagnose faults quickly",
    description: "I need to find out what is wrong with a unit without a laptop.",
    rationale: "Observed on site visits; each delay costs an hour.", status: "active", owner: null,
    version_number: 1, created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

/** A complete email `Engagement` of project-1 with `overrides` applied. */
export function buildEngagement(overrides: Partial<Engagement> = {}): Engagement {
  return {
    id: "engagement-1", project_id: "project-1", creator_id: "user-1", title: "Quarterly review with the regulator",
    channel: "meeting", engagement_date: "2026-03-12", facilitator: null,
    purpose: "Walk through the audit findings.", summary: "Agreed to share evidence by the end of April.",
    notes: "Pat asked for the traceability export.", consent_recorded: true, retain_until: null, retention_due: false,
    participant_count: 1, anonymous_participant_count: 0,
    created_at: "2026-03-12T09:00:00Z", updated_at: "2026-03-12T09:00:00Z",
    ...overrides,
  };
}

/** A research finding of `engagement-1` with `overrides` applied. */
export function buildFinding(overrides: Partial<ResearchFinding> = {}): ResearchFinding {
  return {
    id: "finding-1", project_id: "project-1", engagement_id: "engagement-1", creator_id: "user-1",
    title: "Technicians skip the checklist when offline", description: "Four of five said they note it down later.",
    created_at: "2026-03-12T09:00:00Z", updated_at: "2026-03-12T09:00:00Z",
    ...overrides,
  };
}
