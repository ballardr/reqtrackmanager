/**
 * Fixtures for the external reference stories: a record's references with two systems, and a fake
 * `RecordReferencesApi` whose methods are `fn()` spies, so a story can assert what was called without a network.
 */
import { fn } from "storybook/test";

import type {
  ExternalReference, RecordReferences, RecordReferencesApi, ReferenceFilterApi, ReferenceInput, ReferenceSystem,
} from "../api/externalReferences";

export const REFERENCES_PROJECT_ID = "project-1";

export const REFERENCE_SYSTEMS: ReferenceSystem[] = [
  { id: "s-jira", name: "Jira", url_template: "https://tracker.example/browse/{key}" },
  { id: "s-doors", name: "DOORS", url_template: null },
];

/** A reference; `system` picks Jira (default) or DOORS. */
export function buildReference(overrides: Partial<ExternalReference> = {}, system: "s-jira" | "s-doors" = "s-jira"): ExternalReference {
  const found = REFERENCE_SYSTEMS.find((s) => s.id === system)!;
  return {
    id: `ref-${system}-${overrides.key ?? "PROJ-1"}`, artefact_type: "pain_point", artefact_id: "record-1", system_id: found.id,
    system_name: found.name, key: "PROJ-1", url: null,
    link: found.url_template ? found.url_template.replace("{key}", overrides.key ?? "PROJ-1") : null,
    note: "", role: null, created_by: "u-1", created_at: "2026-11-01T10:00:00Z", ...overrides,
  };
}

/** One record's references and what its editor needs. */
export function buildRecordReferences(overrides: Partial<RecordReferences> = {}): RecordReferences {
  return {
    references: [
      buildReference({ role: "origin", note: "The customer's request" }),
      buildReference({ key: "REQ-9", link: null }, "s-doors"),
    ],
    can_edit: true, systems: REFERENCE_SYSTEMS, ...overrides,
  };
}

/** A fake `RecordReferencesApi`; the writes echo a set that reflects the change. */
export function buildReferencesApi(
  data: RecordReferences = buildRecordReferences(), overrides: Partial<RecordReferencesApi> = {},
): RecordReferencesApi {
  const made = (input: ReferenceInput, id: string): ExternalReference => {
    const system = REFERENCE_SYSTEMS.find((s) => s.id === input.system_id)!;
    return {
      ...buildReference({ id, key: input.key, url: input.url, note: input.note, role: input.role, link: input.url }, system.id as "s-jira"),
      system_id: system.id, system_name: system.name,
    };
  };
  return {
    get: fn(async () => data),
    add: fn(async (_p: string, _t: string, _i: string, input: ReferenceInput) => ({
      ...data, references: [...data.references, made(input, "ref-new")],
    })),
    update: fn(async (_p: string, _t: string, _i: string, referenceId: string, input: ReferenceInput) => ({
      ...data, references: data.references.map((r) => (r.id === referenceId ? made(input, referenceId) : r)),
    })),
    remove: fn(async (_p: string, _t: string, _i: string, referenceId: string) => ({
      ...data, references: data.references.filter((r) => r.id !== referenceId),
    })),
    page: fn(async () => ({})),
    ...overrides,
  };
}

/** A fake `ReferenceFilterApi` offering Jira and DOORS. */
export function buildReferenceFilterApi(names: string[] = ["Jira", "DOORS"]): ReferenceFilterApi {
  return { systems: fn(async () => names) };
}
