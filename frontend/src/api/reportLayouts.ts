/**
 * Module: api/reportLayouts
 *
 * Types and calls for custom report layouts: the list and CRUD of an organisation's or a project's layouts,
 * their version history, the text view conversion, the field and widget catalogues the designer's pickers read,
 * and the draft preview. Layouts live at two tiers with the same shape (`/orgs/{id}/report-layouts`,
 * `/projects/{id}/report-layouts`), so {@link ReportLayoutApi} is one injectable interface bound to a scope by
 * {@link reportLayoutApi}; the project tier adds hiding and restoring inherited layouts.
 *
 * The layout tree (`ReportLayoutTree`) is opaque here: the text view is how a person edits it, and the server
 * validates it, so the client never interprets block shapes.
 */
import { api, ApiError } from "./client";
import type { ReportParam, ReportVariable } from "./reports";

export type LayoutFamily = "document" | "table";
/** Where a project sees a layout from. */
export type LayoutOrigin = "project" | "ancestor" | "organization";

/** What a person calls each family (render enum values through these, never the raw string). */
export const LAYOUT_FAMILY_LABEL: Record<LayoutFamily, string> = { document: "Document", table: "Table" };

/** Where a layout is shared from, as the project's list words it. */
export const LAYOUT_ORIGIN_LABEL: Record<LayoutOrigin, string> = {
  project: "This project",
  ancestor: "A parent project",
  organization: "The organisation",
};

/** The scope a layout list belongs to. */
export interface LayoutScope {
  kind: "organization" | "project";
  id: string;
}

/** The saved JSON tree; opaque to the client. */
export type ReportLayoutTree = Record<string, unknown>;

/** A layout without its tree (`ReportLayoutOut`). */
export interface ReportLayoutSummary {
  id: string;
  organization_id: string;
  project_id: string | null;
  name: string;
  description: string;
  family: LayoutFamily;
  current_version: number;
  origin: LayoutOrigin;
  /** Hidden in the project asking (only ever listed to someone who can manage the project's layouts). */
  hidden: boolean;
  /** The asking scope owns it; an inherited layout is changed where it lives. */
  editable: boolean;
  updated_at: string;
}

/** One saved version with its tree (`ReportLayoutVersionOut`). */
export interface ReportLayoutVersion {
  version: number;
  schema_version: number;
  tree: ReportLayoutTree;
  tree_hash: string;
  comment: string;
  created_by: string | null;
  created_at: string;
}

/** A layout with its current version (`ReportLayoutDetailOut`). */
export interface ReportLayoutDetail extends ReportLayoutSummary {
  current: ReportLayoutVersion;
}

/** A version in the history list (`ReportLayoutVersionSummaryOut`). */
export interface ReportLayoutVersionSummary {
  version: number;
  tree_hash: string;
  comment: string;
  created_by: string | null;
  created_at: string;
}

export interface ReportLayoutCreate {
  name: string;
  description: string;
  family: LayoutFamily;
  tree: ReportLayoutTree;
  comment?: string;
}

/** One problem in the text view: `column` is set for a syntax error, `null` for a validation error of a whole block. */
export interface TextError {
  line: number;
  column: number | null;
  message: string;
}

/** The text read into a tree; `tree` is `null` after a syntax error, `ok` means it may be saved. */
export interface TextParseResult {
  ok: boolean;
  tree: ReportLayoutTree | null;
  errors: TextError[];
}

/** A field of a record type (`ReportFieldOut`). */
export interface ReportFieldInfo {
  key: string;
  label: string;
  /** text, number, date, instant, bool, enum or principal. */
  kind: string;
  /** The engine's own field (code, title, status, tags). */
  reserved: boolean;
  choices: string[];
  /** A text field in which equations (`\( x \)`, `$$ x $$`) are drawn when a text block prints it. */
  math?: boolean;
}

/** A reportable record type with its fields. */
export interface ReportFieldType {
  type: string;
  label: string;
  fields: ReportFieldInfo[];
}

/** What a layout may name (`ReportFieldCatalogueOut`). */
export interface ReportFieldCatalogue {
  types: ReportFieldType[];
  /** Global `{{name}}` placeholders. */
  placeholders: string[];
  /** The fields every group exposes (`{{group.value}}`), with their kinds. */
  group_fields: Record<string, string>;
  schema_version: number;
}

/** One embeddable component of a report (`ReportWidgetOut`). */
export interface ReportWidget {
  key: string;
  title: string;
  description: string;
  /** `section` (a table), `figures` or `notes`. */
  kind: string;
  report_title: string;
  module_key: string;
  module_name: string;
  params: ReportParam[];
}

/** One sheet of a table preview, capped; `total_rows` is the real count. */
export interface PreviewSheet {
  name: string;
  columns: string[];
  rows: string[][];
  total_rows: number;
}

/** What to preview: exactly one of `text` and `tree`, plus the scope's options. */
export interface PreviewRequest {
  text?: string;
  tree?: ReportLayoutTree;
  name?: string;
  /** Project scope: also read readable child projects. */
  include_children?: boolean;
  /** Organisation scope: narrow the fan-out to these projects. */
  project_ids?: string[];
  /** Values for the draft's run-time variables. */
  variables?: Record<string, unknown>;
}

/** The run form of a draft (`ReportLayoutDraftVariablesOut`); with text problems `ok` is false and `errors` names them. */
export interface DraftVariables {
  ok: boolean;
  variables: ReportVariable[];
  errors: TextError[];
}

/** The outcome of a preview; with text problems `ok` is false, `errors` names them and nothing ran. */
export interface PreviewResult {
  ok: boolean;
  errors: TextError[];
  family: LayoutFamily | null;
  /** A standalone, script-free HTML page (document family). */
  html: string | null;
  sheets: PreviewSheet[];
  warnings: string[];
  records_read: number;
  duration_ms: number;
  projects: number;
}

/** The calls the designer and the layout list make, bound to one scope (injectable so stories stay off the network). */
export interface ReportLayoutApi {
  scope: LayoutScope;
  list(): Promise<ReportLayoutSummary[]>;
  create(body: ReportLayoutCreate): Promise<ReportLayoutDetail>;
  get(id: string): Promise<ReportLayoutDetail>;
  versions(id: string): Promise<ReportLayoutVersionSummary[]>;
  version(id: string, version: number): Promise<ReportLayoutVersion>;
  save(id: string, body: { tree: ReportLayoutTree; base_version: number; comment?: string }): Promise<ReportLayoutDetail>;
  update(id: string, body: { name?: string; description?: string }): Promise<ReportLayoutSummary>;
  remove(id: string): Promise<void>;
  parseText(text: string): Promise<TextParseResult>;
  formatTree(tree: ReportLayoutTree): Promise<string>;
  fields(): Promise<ReportFieldCatalogue>;
  widgets(): Promise<ReportWidget[]>;
  preview(body: PreviewRequest): Promise<PreviewResult>;
  /** The draft's run-time variables with their defaults and current options (nothing is stored). */
  draftVariables(text: string): Promise<DraftVariables>;
  /** Project scope only: hides or shows an inherited layout. */
  setHidden?(id: string, hidden: boolean): Promise<ReportLayoutSummary>;
  /** Project scope only: shows the named hidden layouts again. */
  restore?(ids: string[]): Promise<void>;
}

/** The URL prefix of a scope's layouts. */
export function reportLayoutsBase(scope: LayoutScope): string {
  return `/api/v1/${scope.kind === "project" ? "projects" : "orgs"}/${scope.id}/report-layouts`;
}

/** Where the designer for one layout lives. */
export function reportLayoutPath(scope: LayoutScope, layoutId: string): string {
  return `/${scope.kind === "project" ? "projects" : "orgs"}/${scope.id}/report-layouts/${layoutId}`;
}

/** The live implementation of {@link ReportLayoutApi} for an organisation or a project. */
export function reportLayoutApi(scope: LayoutScope): ReportLayoutApi {
  const base = reportLayoutsBase(scope);
  const layouts: ReportLayoutApi = {
    scope,
    list: () => api.get<ReportLayoutSummary[]>(base),
    create: (body) => api.post<ReportLayoutDetail>(base, body),
    get: (id) => api.get<ReportLayoutDetail>(`${base}/${id}`),
    versions: (id) => api.get<ReportLayoutVersionSummary[]>(`${base}/${id}/versions`),
    version: (id, version) => api.get<ReportLayoutVersion>(`${base}/${id}/versions/${version}`),
    save: (id, body) => api.put<ReportLayoutDetail>(`${base}/${id}/tree`, body),
    update: (id, body) => api.patch<ReportLayoutSummary>(`${base}/${id}`, body),
    remove: (id) => api.delete<void>(`${base}/${id}`),
    parseText: (text) => api.post<TextParseResult>(`${base}/text/parse`, { text }),
    formatTree: async (tree) => (await api.post<{ text: string }>(`${base}/text/format`, { tree })).text,
    fields: () => api.get<ReportFieldCatalogue>(`${base}/fields`),
    widgets: () => api.get<ReportWidget[]>(`${base}/widgets`),
    preview: (body) => api.post<PreviewResult>(`${base}/preview`, body),
    draftVariables: (text) => api.post<DraftVariables>(`${base}/variables`, { text }),
  };
  if (scope.kind === "project") {
    layouts.setHidden = (id, hidden) => api.put<ReportLayoutSummary>(`${base}/${id}/visibility`, { hidden });
    layouts.restore = async (ids) => {
      await api.post(`${base}/restore`, { layout_ids: ids });
    };
  }
  return layouts;
}

/** The version a failed save found the layout at (the server's 409), or `null` when the error is not that conflict. */
export function conflictVersion(err: unknown): number | null {
  if (err instanceof ApiError && err.status === 409 && typeof err.detail === "object" && err.detail !== null) {
    const current = (err.detail as { current_version?: unknown }).current_version;
    return typeof current === "number" ? current : null;
  }
  return null;
}

/** The positioned validation problems of a rejected tree (the server's 422), empty when the error is not that. */
export function treeProblems(err: unknown): { path: string; message: string }[] {
  if (err instanceof ApiError && err.status === 422 && typeof err.detail === "object" && err.detail !== null) {
    const errors = (err.detail as { errors?: unknown }).errors;
    if (Array.isArray(errors)) return errors as { path: string; message: string }[];
  }
  return [];
}

/**
 * Creates a copy of a layout in the API's own scope, with the source's current tree: the way to customise a
 * layout shared from elsewhere, which is changed only where it lives.
 *
 * @param api The calls of the scope the copy goes to.
 * @param source The layout to copy (it may belong to another scope the caller can read).
 * @param name The new layout's name.
 * @returns The new layout.
 */
export async function copyReportLayout(api: ReportLayoutApi, source: ReportLayoutSummary, name: string): Promise<ReportLayoutDetail> {
  const detail = await api.get(source.id);
  return api.create({ name, description: source.description, family: source.family, tree: detail.current.tree });
}
