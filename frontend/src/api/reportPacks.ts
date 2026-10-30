/**
 * Module: api/reportPacks
 *
 * Types and calls for report packs: a named list of several reports (custom layouts and module reports), each in its
 * own format, that a person downloads together as one zip with a manifest. Packs live at two tiers with the same
 * shape (`/orgs/{id}/report-packs`, `/projects/{id}/report-packs`), so {@link ReportPackApi} is one injectable
 * interface bound to a scope by {@link reportPackApi}; the project tier adds hiding and restoring inherited packs,
 * overriding an inherited pack's saved sets, and the sets a project adds beside them.
 *
 * Running a pack ({@link reportPackRunApi}) needs only the right to run reports: the run form, the counts preview,
 * the zip download and the hand-off to a background run for a pack that is too big to produce while the person waits.
 * The pack definition (`ReportPackDefinition`) is the server's JSON; the entries editor writes it, the server
 * validates it, and a rejected one comes back as positioned problems ({@link packProblems}).
 */
import { api, ApiError } from "./client";
import type { LayoutOrigin, LayoutScope } from "./reportLayouts";
import type { ReportRun, ReportVariable, VariableValue } from "./reports";

/** Where a project sees a pack from (the same vocabulary as layouts). */
export type PackOrigin = LayoutOrigin;

/** What a person calls each kind of entry (render enum values through these, never the raw string). */
export const PACK_ENTRY_KIND_LABEL: Record<"layout" | "report", string> = {
  layout: "Custom report layout",
  report: "Module report",
};

/** What a person calls each pack entry's status in the counts preview. */
export const PACK_ENTRY_STATUS_LABEL: Record<"included" | "not_available", string> = {
  included: "Included",
  not_available: "Not available",
};

/** The file formats an entry can be produced in: any layout's formats, or any of a module report's. */
export type PackFormat = "pdf" | "docx" | "odt" | "html" | "csv" | "xlsx" | "ods";

/** The formats a module report entry can take: every format the Export menu offers for a report. */
export const REPORT_ENTRY_FORMATS: PackFormat[] = ["pdf", "docx", "odt", "html", "csv", "xlsx", "ods"];

/** One pack variable's declaration (declared as a layout's variables are). */
export interface PackVariableDeclaration {
  name: string;
  type: "text" | "number" | "date" | "bool" | "enum";
  label?: string;
  multiple?: boolean;
  default?: VariableValue;
  options?: string[];
  source?: { record_type: string; field: string };
}

/** A fixed variable value (one value, or a list), as an entry may pin it. */
export type FixedValue = string | number | boolean | (string | number | boolean)[];

/** An entry that runs a custom report layout, named by its name (and optionally which owner's). */
export interface LayoutPackEntry {
  kind: "layout";
  name: string;
  tier?: "organization" | "project";
  format: PackFormat;
  filename?: string;
  variables?: Record<string, FixedValue>;
}

/** An entry that runs a module's report. */
export interface ReportPackReportEntry {
  kind: "report";
  module_key: string;
  report: string;
  format: PackFormat;
  filename?: string;
  params?: Record<string, string | number | boolean>;
}

export type ReportPackEntry = LayoutPackEntry | ReportPackReportEntry;

/** The stored definition of a pack. */
export interface ReportPackDefinition {
  schema_version: number;
  variables?: PackVariableDeclaration[];
  /** Name of an organisation report template whose branding the PDF and Word entries take by default. */
  template?: string;
  /** The zip's default file name, a `{{placeholder}}` template without an extension. */
  file_name?: string;
  entries: ReportPackEntry[];
}

/** A pack without its definition (`ReportPackOut`). */
export interface ReportPackSummary {
  id: string;
  organization_id: string;
  project_id: string | null;
  name: string;
  description: string;
  /** The author's Reports picker folder, up to three levels written `A/B` (`""` = the default folder). */
  folder: string;
  current_version: number;
  origin: PackOrigin;
  /** Hidden in the project asking (only ever listed to someone who can manage the project's packs). */
  hidden: boolean;
  /** The asking scope owns it; an inherited pack is changed where it lives. */
  editable: boolean;
  entries: number;
  /** The record types its reports read, sorted: a record list offers the packs that read its type. */
  record_types: string[];
  updated_at: string;
}

/** One saved version with its definition (`ReportPackVersionOut`). */
export interface ReportPackVersion {
  version: number;
  schema_version: number;
  definition: ReportPackDefinition;
  definition_hash: string;
  comment: string;
  created_by: string | null;
  created_at: string;
}

/** A pack with its current version (`ReportPackDetailOut`). */
export interface ReportPackDetail extends ReportPackSummary {
  current: ReportPackVersion;
}

/** A version in the history list. */
export interface ReportPackVersionSummary {
  version: number;
  definition_hash: string;
  comment: string;
  created_by: string | null;
  created_at: string;
}

export type PackValues = Record<string, VariableValue>;

/** A saved set of values as one scope sees it (`ReportPackSetOut`). */
export interface ReportPackSet {
  id: string;
  name: string;
  /** `pack`: saved with the pack. `project`: added by a project beside the pack's own. */
  origin: "pack" | "project";
  project_id: string | null;
  base: PackValues;
  /** The asking project's own override (a project run only), `null` when it has none. */
  override: PackValues | null;
  /** The nearest project whose override changes a value. */
  overridden_by: string | null;
  /** The values a run for the asking scope takes. */
  effective: PackValues;
  editable: boolean;
  /** The asking project may override its values (an inherited pack's own set). */
  overridable: boolean;
  warnings: string[];
}

/** The calls the pack list and editor make, bound to one scope (injectable so stories stay off the network). */
export interface ReportPackApi {
  scope: LayoutScope;
  list(): Promise<ReportPackSummary[]>;
  create(body: { name: string; description: string; folder?: string; definition: ReportPackDefinition; comment?: string }): Promise<ReportPackDetail>;
  get(id: string): Promise<ReportPackDetail>;
  versions(id: string): Promise<ReportPackVersionSummary[]>;
  save(id: string, body: { definition: ReportPackDefinition; base_version: number; comment?: string }): Promise<ReportPackDetail>;
  update(id: string, body: { name?: string; description?: string; folder?: string }): Promise<ReportPackSummary>;
  remove(id: string): Promise<void>;
  sets(packId: string): Promise<ReportPackSet[]>;
  createSet(packId: string, body: { name: string; values: PackValues }): Promise<ReportPackSet>;
  updateSet(packId: string, setId: string, body: { name?: string; values?: PackValues }): Promise<ReportPackSet>;
  removeSet(packId: string, setId: string): Promise<void>;
  /** Project scope only: hides or shows an inherited pack. */
  setHidden?(id: string, hidden: boolean): Promise<ReportPackSummary>;
  /** Project scope only: shows the named hidden packs again. */
  restore?(ids: string[]): Promise<void>;
  /** Project scope only: this project's values for the variables it changes in an inherited pack's set (none resets). */
  putOverride?(packId: string, setId: string, values: PackValues): Promise<ReportPackSet>;
  /** Project scope only: removes this project's override. */
  resetOverride?(packId: string, setId: string): Promise<ReportPackSet>;
}

/** The URL prefix of a scope's packs. */
export function reportPacksBase(scope: LayoutScope): string {
  return `/api/v1/${scope.kind === "project" ? "projects" : "orgs"}/${scope.id}/report-packs`;
}

/** Where the editor for one pack lives. */
export function reportPackPath(scope: LayoutScope, packId: string): string {
  return `/${scope.kind === "project" ? "projects" : "orgs"}/${scope.id}/report-packs/${packId}`;
}

/** The live implementation of {@link ReportPackApi} for an organisation or a project. */
export function reportPackApi(scope: LayoutScope): ReportPackApi {
  const base = reportPacksBase(scope);
  const packs: ReportPackApi = {
    scope,
    list: () => api.get<ReportPackSummary[]>(base),
    create: (body) => api.post<ReportPackDetail>(base, body),
    get: (id) => api.get<ReportPackDetail>(`${base}/${id}`),
    versions: (id) => api.get<ReportPackVersionSummary[]>(`${base}/${id}/versions`),
    save: (id, body) => api.put<ReportPackDetail>(`${base}/${id}/definition`, body),
    update: (id, body) => api.patch<ReportPackSummary>(`${base}/${id}`, body),
    remove: (id) => api.delete<void>(`${base}/${id}`),
    sets: (packId) => api.get<ReportPackSet[]>(`${base}/${packId}/sets`),
    createSet: (packId, body) => api.post<ReportPackSet>(`${base}/${packId}/sets`, body),
    updateSet: (packId, setId, body) => api.patch<ReportPackSet>(`${base}/${packId}/sets/${setId}`, body),
    removeSet: (packId, setId) => api.delete<void>(`${base}/${packId}/sets/${setId}`),
  };
  if (scope.kind === "project") {
    packs.setHidden = (id, hidden) => api.put<ReportPackSummary>(`${base}/${id}/visibility`, { hidden });
    packs.restore = async (ids) => {
      await api.post(`${base}/restore`, { pack_ids: ids });
    };
    packs.putOverride = (packId, setId, values) => api.put<ReportPackSet>(`${base}/${packId}/sets/${setId}/override`, { values });
    packs.resetOverride = (packId, setId) => api.delete<ReportPackSet>(`${base}/${packId}/sets/${setId}/override`);
  }
  return packs;
}

// --- running -----------------------------------------------------------------------------------------------

/** A saved set offered on the run form: the values a run would take. */
export interface ReportPackFormSet {
  id: string;
  name: string;
  values: PackValues;
  warnings: string[];
}

/** What a run asks of the person (`ReportPackFormOut`). */
export interface ReportPackForm {
  name: string;
  description: string;
  entries: number;
  variables: ReportVariable[];
  sets: ReportPackFormSet[];
}

/** What to run: the values typed, the saved set started from and the scope's options. */
export interface ReportPackRunBody {
  variables?: PackValues;
  variable_set_id?: string | null;
  report_template_id?: string | null;
  include_children?: boolean;
  project_ids?: string[];
}

/** What one entry would produce (`ReportPackPreviewEntryOut`). */
export interface ReportPackPreviewEntry {
  position: number;
  kind: "layout" | "report";
  title: string;
  format: string;
  status: "included" | "not_available";
  reason: string | null;
  records: number;
  warnings: string[];
}

/** The counts per entry for the chosen values (`ReportPackPreviewOut`). */
export interface ReportPackPreview {
  entries: ReportPackPreviewEntry[];
  total_records: number;
  not_available: number;
  variable_set: string | null;
  warnings: string[];
}

/** The calls that run one pack, bound to a scope and a pack. */
export interface ReportPackRunApi {
  form(): Promise<ReportPackForm>;
  preview(body: ReportPackRunBody): Promise<ReportPackPreview>;
  /** Produces the zip while the person waits (a pack over the bounds answers `async_required`; see `isAsyncRequired`). */
  download(body: ReportPackRunBody): Promise<Blob>;
  /** Queues the pack to be produced in the background; the person is notified when the zip is ready. */
  queue(body: ReportPackRunBody): Promise<ReportRun>;
}

/** The live {@link ReportPackRunApi} for one pack. */
export function reportPackRunApi(scope: LayoutScope, packId: string): ReportPackRunApi {
  const base = `${reportPacksBase(scope)}/${packId}`;
  return {
    form: () => api.get<ReportPackForm>(`${base}/form`),
    preview: (body) => api.post<ReportPackPreview>(`${base}/preview`, body),
    download: (body) => api.postForBlob(`${base}/run`, body),
    queue: (body) => api.post<ReportRun>(`${base}/runs`, body),
  };
}

/** The positioned problems of a rejected definition (the server's 422), empty when the error is not that. */
export function packProblems(err: unknown): { path: string; message: string }[] {
  if (err instanceof ApiError && err.status === 422 && typeof err.detail === "object" && err.detail !== null) {
    const errors = (err.detail as { errors?: unknown }).errors;
    if (Array.isArray(errors)) return errors as { path: string; message: string }[];
  }
  return [];
}

/** The `detail.code` of the 409 a run answers when no entry of the pack can be produced here. */
export const NOTHING_TO_RUN = "nothing_to_run";

/** Whether `err` is the answer that no entry of the pack can be produced. */
export function isNothingToRun(err: unknown): boolean {
  return (
    err instanceof ApiError &&
    err.status === 409 &&
    typeof err.detail === "object" &&
    err.detail !== null &&
    (err.detail as { code?: unknown }).code === NOTHING_TO_RUN
  );
}

/** An empty definition: a pack with no reports yet. */
export function emptyPackDefinition(): ReportPackDefinition {
  return { schema_version: 1, entries: [] };
}
