/**
 * Module: testing/reportPackFixtures
 *
 * Storybook-only builders for the report pack screens: packs, saved sets, the run form and a fake `ReportPackApi` /
 * `ReportPackRunApi` whose methods are `fn()` spies. The fake keeps its packs and sets in memory, so a story can
 * create, rename, override or hide and read the change back. The real validation, run and counts are the server's
 * and are covered by the backend tests.
 */
import { fn } from "storybook/test";

import type {
  PackValues, ReportPackApi, ReportPackDefinition, ReportPackDetail, ReportPackForm, ReportPackPreview, ReportPackRunApi,
  ReportPackSet, ReportPackSummary,
} from "../api/reportPacks";
import type { ReportRun, ReportVariable } from "../api/reports";

/** The pack variable most stories use: categories of requirements, several allowed. */
export function buildCategoriesVariable(overrides: Partial<ReportVariable> = {}): ReportVariable {
  return {
    name: "categories", type: "enum", label: "Categories", multiple: true, default: null,
    options: ["Security", "Usability", "Billing"], source: { record_type: "requirement", field: "category" }, ...overrides,
  };
}

/** A definition with two layouts and one module report, and the categories variable. */
export function buildDefinition(overrides: Partial<ReportPackDefinition> = {}): ReportPackDefinition {
  return {
    schema_version: 1,
    variables: [{ name: "categories", type: "enum", label: "Categories", multiple: true, source: { record_type: "requirement", field: "category" } }],
    entries: [
      { kind: "layout", name: "Requirements overview", format: "pdf", filename: "overview" },
      { kind: "layout", name: "Requirement rows", format: "xlsx" },
      { kind: "report", module_key: "decisions", report: "d1", format: "csv", filename: "decisions" },
    ],
    ...overrides,
  };
}

/** A pack summary (the project's own, editable). */
export function buildPackSummary(overrides: Partial<ReportPackSummary> = {}): ReportPackSummary {
  return {
    id: "pack-1", organization_id: "org-1", project_id: "project-1", name: "Handover pack", description: "For the external team.",
    current_version: 2, origin: "project", hidden: false, editable: true, entries: 3, updated_at: "2026-10-20T09:30:00Z", ...overrides,
  };
}

/** A pack with its current version. */
export function buildPackDetail(overrides: Partial<ReportPackDetail> = {}, definition = buildDefinition()): ReportPackDetail {
  const summary = buildPackSummary(overrides);
  return {
    ...summary,
    current: {
      version: summary.current_version, schema_version: 1, definition, definition_hash: "hash", comment: "Added the rows",
      created_by: "user-1", created_at: "2026-10-12T09:00:00Z",
    },
    ...overrides,
  };
}

/** A saved set saved with the pack. */
export function buildSet(overrides: Partial<ReportPackSet> = {}): ReportPackSet {
  const base: PackValues = overrides.base ?? { categories: ["Security"] };
  return {
    id: "set-1", name: "Team Alpha", origin: "pack", project_id: null, base, override: null, overridden_by: null,
    effective: base, editable: true, overridable: false, warnings: [], ...overrides,
  };
}

/** The run form of a pack. */
export function buildForm(overrides: Partial<ReportPackForm> = {}): ReportPackForm {
  return {
    name: "Handover pack", description: "For the external team.", entries: 3, variables: [buildCategoriesVariable()],
    sets: [{ id: "set-1", name: "Team Alpha", values: { categories: ["Security"] }, warnings: [] }], ...overrides,
  };
}

/** The counts preview of a pack: two reports included, one not available. */
export function buildPreview(overrides: Partial<ReportPackPreview> = {}): ReportPackPreview {
  return {
    entries: [
      { position: 1, kind: "layout", title: "Requirements overview", format: "pdf", status: "included", reason: null, records: 12, warnings: [] },
      { position: 2, kind: "layout", title: "Requirement rows", format: "xlsx", status: "included", reason: null, records: 12, warnings: [] },
      { position: 3, kind: "report", title: "Decision register", format: "csv", status: "not_available", reason: "Its module is not enabled for this project.", records: 0, warnings: [] },
    ],
    total_records: 24, not_available: 1, variable_set: null, warnings: [], ...overrides,
  };
}

/** A queued background run. */
export function buildRun(overrides: Partial<ReportRun> = {}): ReportRun {
  return {
    id: "run-1", organization_id: "org-1", project_id: "project-1", scope: "project", layout_name: "Handover pack", layout_version: 2,
    format: "zip", status: "queued", created_at: "2026-10-27T09:00:00Z", started_at: null, finished_at: null, expires_at: null,
    output_filename: null, output_size: null, error: null, ...overrides,
  };
}

/** A fake `ReportPackRunApi`; override any call. */
export function buildRunApi(overrides: Partial<ReportPackRunApi> = {}): ReportPackRunApi {
  return {
    form: fn(async () => buildForm()),
    preview: fn(async () => buildPreview()),
    download: fn(async () => new Blob(["zip"], { type: "application/zip" })),
    queue: fn(async () => buildRun()),
    ...overrides,
  };
}

/**
 * An in-memory `ReportPackApi`. `packs` are the scope's packs (the first is opened by `get`); `initialSets` its saved sets.
 * `stateful: false` makes writes answer as if they worked without remembering them, for stories sharing one api.
 */
export function buildPackApi(
  packs: ReportPackSummary[] = [buildPackSummary()],
  overrides: Partial<ReportPackApi> & { kind?: "project" | "organization"; stateful?: boolean; initialSets?: ReportPackSet[] } = {},
): ReportPackApi {
  const stateful = overrides.stateful !== false;
  const store = packs.map((pack) => ({ ...pack }));
  const setStore = (overrides.initialSets ?? [buildSet()]).map((set) => ({ ...set }));
  const kind = overrides.kind ?? "project";
  const fake: ReportPackApi = {
    scope: { kind, id: kind === "project" ? "project-1" : "org-1" },
    list: fn(async () => store.map((pack) => ({ ...pack }))),
    create: fn(async (body) => {
      const created = buildPackSummary({ id: `pack-${store.length + 1}`, name: body.name, description: body.description, current_version: 1, entries: body.definition.entries.length });
      store.push(created);
      return { ...created, current: { ...buildPackDetail().current, version: 1, definition: body.definition } };
    }),
    get: fn(async (id: string) => {
      const found = store.find((pack) => pack.id === id) ?? store[0];
      return buildPackDetail(found);
    }),
    versions: fn(async () => [
      { version: 2, definition_hash: "h2", comment: "Added the rows", created_by: "user-1", created_at: "2026-10-12T09:00:00Z" },
      { version: 1, definition_hash: "h1", comment: "First draft", created_by: "user-1", created_at: "2026-10-11T09:00:00Z" },
    ]),
    save: fn(async (id: string, body: { definition: ReportPackDefinition; base_version: number }) => {
      const found = store.find((pack) => pack.id === id) ?? store[0];
      const next = body.base_version + 1;
      if (stateful) found.current_version = next;
      return { ...buildPackDetail({ ...found, current_version: next }), current: { ...buildPackDetail().current, version: next, definition: body.definition } };
    }),
    update: fn(async (id: string, body: { name?: string; description?: string }) => {
      const found = store.find((pack) => pack.id === id) ?? store[0];
      if (stateful) Object.assign(found, body);
      return { ...found, ...body };
    }),
    remove: fn(async (id: string) => {
      const at = store.findIndex((pack) => pack.id === id);
      if (stateful && at >= 0) store.splice(at, 1);
    }),
    sets: fn(async () => setStore.map((set) => ({ ...set }))),
    createSet: fn(async (_packId: string, body: { name: string; values: PackValues }) => {
      const created = buildSet({ id: `set-${setStore.length + 1}`, name: body.name, base: body.values, effective: body.values });
      if (stateful) setStore.push(created);
      return created;
    }),
    updateSet: fn(async (_packId: string, setId: string, body: { name?: string; values?: PackValues }) => {
      const found = setStore.find((set) => set.id === setId) ?? setStore[0];
      if (stateful) {
        if (body.name !== undefined) found.name = body.name;
        if (body.values !== undefined) { found.base = body.values; found.effective = body.values; }
      }
      return { ...found };
    }),
    removeSet: fn(async (_packId: string, setId: string) => {
      const at = setStore.findIndex((set) => set.id === setId);
      if (stateful && at >= 0) setStore.splice(at, 1);
    }),
  };
  if (kind === "project") {
    fake.setHidden = fn(async (id: string, hidden: boolean) => {
      const found = store.find((pack) => pack.id === id) ?? store[0];
      found.hidden = hidden;
      return { ...found };
    });
    fake.restore = fn(async (ids: string[]) => {
      for (const pack of store) if (ids.includes(pack.id)) pack.hidden = false;
    });
    fake.putOverride = fn(async (_packId: string, setId: string, values: PackValues) => {
      const found = setStore.find((set) => set.id === setId) ?? setStore[0];
      if (stateful) { found.override = values; found.effective = { ...found.base, ...values }; found.overridden_by = "project-1"; }
      return { ...found };
    });
    fake.resetOverride = fn(async (_packId: string, setId: string) => {
      const found = setStore.find((set) => set.id === setId) ?? setStore[0];
      if (stateful) { found.override = null; found.effective = found.base; found.overridden_by = null; }
      return { ...found };
    });
  }
  const { kind: _kind, stateful: _stateful, initialSets: _sets, ...rest } = overrides;
  void _kind;
  void _stateful;
  void _sets;
  return { ...fake, ...rest };
}
