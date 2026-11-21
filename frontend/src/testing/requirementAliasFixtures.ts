/**
 * Module: testing/requirementAliasFixtures
 *
 * Builders and fakes for the requirement alias stories: a small project tree (Software with Performance, Hardware
 * with Cooling and Power), a requirement that sits in Software / Performance with one alias in Hardware / Cooling, and
 * a fake `RequirementAliasesApi` whose methods are `fn()` spies, so a story states only what it is about.
 */
import { fn } from "storybook/test";

import type { ArtefactLinksApi } from "../api/artefactLinks";
import type { PlacementTree, RecordPlacementsApi } from "../api/placements";
import type { AliasSettings, IndependentResult, RequirementAliasesApi } from "../api/requirementAliases";
import type { Requirement, RequirementAlias } from "../api/types";
import { buildOption } from "./artefactLinksFixtures";
import { buildRequirement } from "./storybook-helpers";

export const ALIAS_PROJECT_ID = "project-1";

/** Software (Performance) and Hardware (Cooling and Power). */
export function buildAliasTree(): PlacementTree {
  const base = { project_id: ALIAS_PROJECT_ID };
  return {
    components: [
      { ...base, id: "c-sw", name: "Software", prefix: "SW", sort_order: 0 },
      { ...base, id: "c-hw", name: "Hardware", prefix: "HW", sort_order: 1 },
    ],
    categories: [
      { ...base, id: "k-perf", component_id: "c-sw", name: "Performance", prefix: "PERF", sort_order: 0 },
      { ...base, id: "k-cool", component_id: "c-hw", name: "Cooling", prefix: "COOL", sort_order: 0 },
      { ...base, id: "k-power", component_id: "c-hw", name: "Power", prefix: "PWR", sort_order: 1 },
    ],
  };
}

/** The alias in Hardware / Cooling. */
export function buildAlias(overrides: Partial<RequirementAlias> = {}): RequirementAlias {
  return { id: "alias-1", unique_code: "HW-COOL-002", component_id: "c-hw", category_id: "k-cool", is_retired: false, ...overrides };
}

/** A requirement in Software / Performance with one alias (a locked, approved one when `approved`). */
export function buildAliasedRequirement(overrides: Partial<Requirement> = {}, approved = false): Requirement {
  return buildRequirement({
    id: "req-1", unique_code: "SW-PERF-001", component_id: "c-sw", category_id: "k-perf", aliases: [buildAlias()],
    ...(approved ? { status: "approved" as const } : {}), ...overrides,
  });
}

export function buildAliasSettings(overrides: Partial<AliasSettings> = {}): AliasSettings {
  return {
    mode: "allowed", source: "organization", own_mode: null, organization_mode: "allowed", has_parent: false, alias_count: 1,
    ...overrides,
  };
}

export function buildIndependentResult(overrides: Partial<IndependentResult> = {}): IndependentResult {
  return {
    requirement_id: "req-2", unique_code: "HW-COOL-002", original_id: "req-1", links_copied: 1, comments_copied: 2,
    attachments_copied: 0, tags_copied: 1, related_link_made: true, skipped: [], ...overrides,
  };
}

/** A fake `RequirementAliasesApi`; each write answers with what the real one would. */
export function buildAliasesApi(
  settings: AliasSettings = buildAliasSettings(), overrides: Partial<RequirementAliasesApi> = {},
): RequirementAliasesApi {
  return {
    settings: fn(async () => settings),
    setProjectMode: fn(async (_p: string, mode) => ({ ...settings, own_mode: mode, mode: mode ?? settings.organization_mode })),
    organizationMode: fn(async () => settings.organization_mode),
    setOrganizationMode: fn(async (_o: string, mode) => mode),
    setPlaces: fn(async () => buildAliasedRequirement()),
    retire: fn(async () => buildAliasedRequirement({ aliases: [] })),
    promote: fn(async () => buildAliasedRequirement({ unique_code: "HW-COOL-002", component_id: "c-hw", category_id: "k-cool" })),
    makeIndependent: fn(async () => buildIndependentResult()),
    makeAllIndependent: fn(async () => ({ made: [buildIndependentResult()], failed: [] })),
    ...overrides,
  };
}

/** A fake placements API that only reads the tree. */
export function buildTreeApi(): RecordPlacementsApi {
  return {
    get: fn(async () => ({ placements: [], can_edit: true, managed_on_record: true })),
    set: fn(async () => ({ placements: [], can_edit: true, managed_on_record: true })),
    tree: fn(async () => buildAliasTree()),
    page: fn(async () => ({})),
  };
}

/** A fake links API offering "Related to" (or, with `withoutRelated`, only a directional type). */
export function buildOptionsApi(withoutRelated = false): ArtefactLinksApi {
  const options = withoutRelated
    ? [buildOption({ link_type_id: "lt-derives", forward_name: "Derives from", reverse_name: "Is source of", flow: "forward_is_upstream", phrase: "Derives from" })]
    : [buildOption()];
  return { options: fn(async () => options) } as unknown as ArtefactLinksApi;
}
