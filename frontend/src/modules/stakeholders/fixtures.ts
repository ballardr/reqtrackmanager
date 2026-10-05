/**
 * Module: modules/stakeholders/fixtures
 *
 * Shared Storybook fixtures for the stakeholders module's stories — a
 * `Persona` builder so every story constructs the same complete wire shape.
 */
import type { Persona } from "./types";

/** A complete project-scoped, active `Persona` with `overrides` applied. */
export function buildPersona(overrides: Partial<Persona> = {}): Persona {
  return {
    id: "persona-1", scope: "project", organization_id: null, project_id: "project-1", creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null, name: "Field Technician",
    description: "Inspects equipment on site.", persona_type_id: "type-primary", persona_type_name: "Primary",
    role_title: "Senior technician", goals: "Finish inspections without rework.", needs: "Offline access.",
    behaviours: "Works in short bursts between sites.", context_environment: "Outdoors, gloves on.",
    skills_proficiency: "Expert with the equipment.", frequency_of_use: "Daily", constraints: "No reliable network.",
    weight: 2, status: "active", owner_id: null, champion_id: null, version_number: 1,
    effective_weight: 2, weight_override: null, weight_source: "persona",
    created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}
