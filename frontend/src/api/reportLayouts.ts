/**
 * Module: api/reportLayouts
 *
 * Types and calls for custom report layouts: the list and CRUD of an organisation's or a project's layouts,
 * their version history, the text view conversion, the field and widget catalogues the designer's pickers read,
 * and the draft preview. Layouts live at two tiers with the same shape (`/orgs/{id}/report-layouts`,
 * `/projects/{id}/report-layouts`), so {@link ReportLayoutApi} is one injectable interface bound to a scope by
 * {@link reportLayoutApi}; the project tier adds hiding and restoring inherited layouts.
 *
 * The layout tree (`ReportLayoutTree`) is plain JSON. The server stays the only parser and validator: the block
 * outline edits the tree through the schemas `blocks()` publishes (so a module's block type needs no client
 * code) and asks `validate()` after every change; the client never reads or checks a block's content itself
 * beyond placing it in the tree.
 */
import { api, ApiError } from "./client";
import { fetchFileDetails, type FileDetails } from "./fileDetails";
import type { ReportFileKind, ReportParam, ReportVariable } from "./reports";
import type { ColourContext } from "../utils/reportColours";

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

/** A picture in a layout tier's library (`ReportImageOut`): what an image block can show. */
export interface ReportImage {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  /** `organisation` (every project's layouts can use it) or `project`. */
  tier: "organisation" | "project";
  /** The library asking owns it, so its manager can delete it. */
  owned: boolean;
  /** Names of the layouts whose current version uses it. */
  used_by: string[];
  /** No current version uses it, but an older saved version of some layout does. */
  in_older_versions: boolean;
  created_at: string;
}

/**
 * A library listing: the pictures, the largest file an upload may be (a deployment setting) and whether EPS and PDF
 * files can be uploaded (the deployment runs the optional converter service).
 */
export interface ReportImageList {
  images: ReportImage[];
  max_image_bytes: number;
  converter_available: boolean;
}

/** The calls the image picker makes (the layout API's, narrowed so a story can supply a few pictures). */
export interface ReportImageLibrary {
  list(): Promise<ReportImageList>;
  /** What a picture says about itself (EXIF and size), to choose between photographs. */
  details(id: string): Promise<FileDetails>;
  upload(file: File): Promise<ReportImage>;
  remove(id: string): Promise<void>;
}

/** The saved JSON tree (see the module note: edited through block schemas, validated by the server). */
export type ReportLayoutTree = Record<string, unknown>;

/** A layout without its tree (`ReportLayoutOut`). */
export interface ReportLayoutSummary {
  id: string;
  organization_id: string;
  project_id: string | null;
  name: string;
  description: string;
  /** The author's Reports picker folder, up to three levels written `A/B` (`""` = the default folder). */
  folder: string;
  /** The branding template this layout's documents use; `null` follows the organisation's default. */
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

/** Who holds unpublished work on a layout, with no tree (`ReportLayoutDraftSummaryOut`). */
export interface ReportLayoutDraftSummary {
  /** The version the draft was started from; behind the layout's `current_version` when one was published since. */
  base_version: number;
  /** Changes with every write; a write or a publish names the one it saw. */
  revision: number;
  updated_by: string | null;
  updated_by_name: string | null;
  updated_at: string;
}

/** The shared draft with its tree (`ReportLayoutDraftOut`); the tree may be invalid, `problems` says why it cannot be published. */
export interface ReportLayoutDraft extends ReportLayoutDraftSummary {
  tree: ReportLayoutTree;
  tree_hash: string;
  problems: TreeProblem[];
}

/** The outcome of an autosave: the draft now stored, or `null` when the tree equals the saved version and none is kept. */
export interface ReportLayoutDraftSaved {
  draft: ReportLayoutDraft | null;
}

/** A layout with its current version (`ReportLayoutDetailOut`); `draft` is set only for a layout the asking scope owns. */
export interface ReportLayoutDetail extends ReportLayoutSummary {
  current: ReportLayoutVersion;
  draft?: ReportLayoutDraftSummary | null;
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
  folder?: string;
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
  /** The 1-based line each block starts on, by tree path (`nodes[2]`, `nodes[2].children[0]`); empty after a syntax error. */
  block_lines?: Record<string, number>;
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

/** One key of a block or of the layout as the outline's form offers it (`ReportBlockFieldOut`). */
export interface BlockField {
  key: string;
  label: string;
  /** Which control draws it (one of `BlockCatalogue.field_kinds`; an unknown kind is shown as JSON). */
  kind: string;
  required: boolean;
  help: string;
  max_length: number | null;
  minimum: number | null;
  maximum: number | null;
  default: unknown;
  choices: string[];
  /** What a text may contain: `placeholders`, `math`, `markdown`. */
  features: string[];
  /** The key of a sibling field this one reads. */
  depends_on: string | null;
  /** Families it applies to; empty means all. */
  families: string[];
  /** What an empty value means ("Auto"), shown in the empty box; `""` for none. */
  empty_label: string;
  /** The key of the `BlockGroup` it sits in; `""` for the form's basic part. */
  group: string;
  /** Stays visible although the form is arranged in groups. */
  basic: boolean;
  /** `choice-buttons` or `toggle`: how it is drawn instead of its kind's usual control; `""` for the usual one. */
  control: string;
  /** Drawn on the same row as the field before it (a value and its unit). */
  inline: boolean;
}

/** A collapsible group of a block's fields. */
export interface BlockGroup {
  key: string;
  label: string;
  /** Starts open (a block with no basic part); a person's own choice wins. */
  open: boolean;
}

/** A list of child blocks a block holds. */
export interface BlockContainer {
  key: string;
  label: string;
}

/** A name a block brings into scope: `key` holds it, `kind` is `record` or `group`, `default` is used when absent. */
export interface BlockProvides {
  key: string;
  kind: "record" | "group";
  default: string;
}

/** One block type the outline can add (`ReportBlockOut`). */
export interface BlockType {
  type: string;
  label: string;
  description: string;
  families: LayoutFamily[];
  fields: BlockField[];
  containers: BlockContainer[];
  provides: BlockProvides | null;
  /** The node a new block starts as (may fail validation until the author fills it in). */
  template: Record<string, unknown>;
  /** False for a type that declared no form; the outline shows its node as JSON. */
  described: boolean;
  /** The groups its fields are arranged in, in order; empty for a flat form. */
  groups: BlockGroup[];
}

/** Every block type, the layout-level fields and the control kinds the outline can draw (`ReportBlockCatalogueOut`). */
export interface BlockCatalogue {
  blocks: BlockType[];
  layout_fields: BlockField[];
  /** The settings of an image column (the pictures attached to each row's record), drawn with the shared field forms. */
  image_column_fields: BlockField[];
  field_kinds: string[];
  /** The operators a condition accepts on a field of each kind (`text`, `enum`, `number`, `date`, …). */
  operators: Record<string, string[]>;
  /** Operators that take no value (`empty`, `not_empty`). */
  valueless_operators: string[];
  /** Operators that take a list of values (`in`, `not_in`). */
  list_operators: string[];
  schema_version: number;
}

/** One problem in a tree: `path` is where (`nodes[2].children[0].columns[1].field`; empty for the layout itself). */
export interface TreeProblem {
  path: string;
  message: string;
}

/** The outcome of checking a tree (`ReportLayoutValidateOut`). */
export interface TreeCheck {
  ok: boolean;
  errors: TreeProblem[];
  node_count: number;
  /** Things that do not stop a save or a run, for example a font this server does not have. */
  warnings?: string[];
}

/** A font family an author may choose for a layout — `GET /system/report-fonts/choices`. */
export interface ReportFontChoice {
  key: string;
  label: string;
  /** `true` for the four standard fonts; `false` for one the server administrator provides. */
  bundled: boolean;
  generic: "sans-serif" | "serif" | "monospace";
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

/** The output formats a snippet's result is true in. */
export type SnippetFormat = "html" | "pdf" | "docx" | "odt";

/** What a person calls each output format. */
export const SNIPPET_FORMAT_LABEL: Record<SnippetFormat, string> = { html: "HTML", pdf: "PDF", docx: "Word", odt: "OpenDocument" };

/** What a snippet parameter asks for: a library picture, a record type the scope can report, or a short text. */
export type SnippetParameterKind = "image" | "record_type" | "text";

/** One choice the person makes when inserting a snippet (`ReportSnippetParameterOut`). */
export interface SnippetParameter {
  key: string;
  label: string;
  kind: SnippetParameterKind;
  help: string;
  required: boolean;
  default: string | null;
  max_length: number | null;
  /** The record types to choose from (`record_type` only). */
  choices: { value: string; label: string }[];
}

/** A snippet a scope can insert (`ReportSnippetOut`). `module_key` is `null` for a platform snippet; `saved_id` is set for one an author saved. */
export interface ReportSnippet {
  key: string;
  name: string;
  description: string;
  category: string;
  family: LayoutFamily;
  formats: SnippetFormat[];
  module_key: string | null;
  /** The saved snippet's id and where this scope sees it from; `null` for a built-in or module snippet. */
  saved_id?: string | null;
  origin?: LayoutOrigin | null;
  parameters: SnippetParameter[];
  /** The fragment, for the picker's outline. */
  blocks: Record<string, unknown>[];
}

/** Where a snippet goes: a list of blocks (`nodes`, `nodes[2].children`) and an index in it (`null`: the end). */
export interface SnippetTarget {
  container: string;
  index: number | null;
}

/** The result of inserting a snippet into a draft (`ReportSnippetApplyOut`); nothing is stored. */
export interface SnippetApplyResult {
  ok: boolean;
  tree: ReportLayoutTree | null;
  changes: string[];
  errors: { path: string; message: string }[];
  /** The path of the first inserted block (`nodes[3]`). */
  inserted_at: string | null;
  count: number;
  /** How many problems the layout already had, which the insertion left alone. */
  problems_elsewhere: number;
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
  /** The layout's shared draft with its tree (404 when there is none). */
  draft(id: string): Promise<ReportLayoutDraft>;
  /** Autosaves the editor's tree into the shared draft; `revision` is the one the editor last saw (`0`: none). A moved draft answers 409 (`draftConflict`). */
  writeDraft(id: string, body: { tree: ReportLayoutTree; base_version: number; revision: number }): Promise<ReportLayoutDraftSaved>;
  /** Discards the shared draft (the work in it is lost). */
  discardDraft(id: string): Promise<void>;
  /** Publishes the shared draft as the next version and removes it; `draft_revision` is the one the publisher saw. */
  publishDraft(id: string, body: { draft_revision: number; comment?: string }): Promise<ReportLayoutDetail>;
  update(
    id: string, body: { name?: string; description?: string; folder?: string },
  ): Promise<ReportLayoutSummary>;
  remove(id: string): Promise<void>;
  parseText(text: string): Promise<TextParseResult>;
  formatTree(tree: ReportLayoutTree): Promise<string>;
  fields(): Promise<ReportFieldCatalogue>;
  widgets(): Promise<ReportWidget[]>;
  /** The block types the outline can add, with the form each needs. */
  blocks(): Promise<BlockCatalogue>;
  /** The organisation's branding colour and colour scheme, for the colour fields (stock values where a client has no call). */
  colours?(): Promise<ColourContext>;
  /** The fonts an author may choose (stock four where a client has no call). */
  fonts?(): Promise<ReportFontChoice[]>;
  /** Checks a draft tree and lists every problem with its path (nothing is stored). */
  validate(tree: ReportLayoutTree): Promise<TreeCheck>;
  /** The snippets the scope can insert, with each parameter's choices. */
  snippets(): Promise<ReportSnippet[]>;
  /** Builds the draft tree with a snippet inserted (200 either way: a refusal lists why; nothing is stored). */
  applySnippet(key: string, body: { tree: ReportLayoutTree; parameters: Record<string, string>; target: SnippetTarget }): Promise<SnippetApplyResult>;
  /** The picture library an image block draws from: this scope's own pictures and, for a project, the organisation's. */
  images: ReportImageLibrary;
  preview(body: PreviewRequest): Promise<PreviewResult>;
  /**
   * Renders the draft as a file in `format` (a format of its family) without saving: nothing is stored and no run is
   * recorded. A draft too big to produce while the author waits answers `async_required` (`isAsyncRequired`); a preview is never queued.
   */
  downloadPreview(body: PreviewRequest, format: ReportFileKind): Promise<Blob>;
  /** The draft's run-time variables with their defaults and current options (nothing is stored). */
  draftVariables(text: string): Promise<DraftVariables>;
  /** Organisation scope only: the names of the starter layouts the organisation lacks (empty when every starter is present). */
  missingStarters?(): Promise<string[]>;
  /** Organisation scope only: writes the starter layouts the organisation lacks; resolves to the names added. */
  addStarters?(): Promise<string[]>;
  /** Project scope only: hides or shows an inherited layout. */
  setHidden?(id: string, hidden: boolean): Promise<ReportLayoutSummary>;
  /** Project scope only: shows the named hidden layouts again. */
  restore?(ids: string[]): Promise<void>;
}

/** The URL prefix of a scope's layouts. */
export function reportLayoutsBase(scope: LayoutScope): string {
  return `/api/v1/${scope.kind === "project" ? "projects" : "orgs"}/${scope.id}/report-layouts`;
}

/** The URL prefix of a scope's picture library. */
export function reportImagesBase(scope: LayoutScope): string {
  return `/api/v1/${scope.kind === "project" ? "projects" : "orgs"}/${scope.id}/report-images`;
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
    draft: (id) => api.get<ReportLayoutDraft>(`${base}/${id}/draft`),
    writeDraft: (id, body) => api.put<ReportLayoutDraftSaved>(`${base}/${id}/draft`, body),
    discardDraft: (id) => api.delete<void>(`${base}/${id}/draft`),
    publishDraft: (id, body) => api.put<ReportLayoutDetail>(`${base}/${id}/tree`, { from_draft: true, ...body }),
    update: (id, body) => api.patch<ReportLayoutSummary>(`${base}/${id}`, body),
    remove: (id) => api.delete<void>(`${base}/${id}`),
    parseText: (text) => api.post<TextParseResult>(`${base}/text/parse`, { text }),
    formatTree: async (tree) => (await api.post<{ text: string }>(`${base}/text/format`, { tree })).text,
    fields: () => api.get<ReportFieldCatalogue>(`${base}/fields`),
    widgets: () => api.get<ReportWidget[]>(`${base}/widgets`),
    blocks: () => api.get<BlockCatalogue>(`${base}/blocks`),
    colours: () => api.get<ColourContext>(`${base}/colours`),
    fonts: () => api.get<ReportFontChoice[]>("/api/v1/system/report-fonts/choices"),
    validate: (tree) => api.post<TreeCheck>(`${base}/validate`, { tree }),
    snippets: () => api.get<ReportSnippet[]>(`${base}/snippets`),
    applySnippet: (key, body) => api.post<SnippetApplyResult>(`${base}/snippets/${encodeURIComponent(key)}/apply`, body),
    preview: (body) => api.post<PreviewResult>(`${base}/preview`, body),
    downloadPreview: (body, format) => api.postForFile(`${base}/preview/download`, { ...body, format }),
    draftVariables: (text) => api.post<DraftVariables>(`${base}/variables`, { text }),
    images: {
      list: () => api.get<ReportImageList>(reportImagesBase(scope)),
      details: fetchFileDetails,
      upload: (file) => api.postFile<ReportImage>(reportImagesBase(scope), file),
      remove: (id) => api.delete<void>(`${reportImagesBase(scope)}/${id}`),
    },
  };
  if (scope.kind === "organization") {
    layouts.missingStarters = async () => (await api.get<{ missing: string[] }>(`${base}/starters`)).missing;
    layouts.addStarters = async () => (await api.post<{ added: string[] }>(`${base}/starters`, {})).added;
  }
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

/** A draft without its tree and problems: what the designer keeps to word the notice and the status line. */
export function draftSummary(draft: ReportLayoutDraftSummary): ReportLayoutDraftSummary {
  return {
    base_version: draft.base_version, revision: draft.revision, updated_by: draft.updated_by,
    updated_by_name: draft.updated_by_name, updated_at: draft.updated_at,
  };
}

/**
 * What a rejected draft write or publish found: the draft as it stands now (`draft`, `null` when it was published or
 * discarded meanwhile), or `undefined` when the error is not the draft-moved conflict.
 */
export function draftConflict(err: unknown): { draft: ReportLayoutDraftSummary | null } | undefined {
  if (err instanceof ApiError && err.status === 409 && typeof err.detail === "object" && err.detail !== null) {
    const detail = err.detail as { code?: unknown; draft?: unknown };
    if (detail.code === "draft_conflict") return { draft: (detail.draft as ReportLayoutDraftSummary | null | undefined) ?? null };
  }
  return undefined;
}

/** The positioned validation problems of a rejected tree (the server's 422), empty when the error is not that. */
export function treeProblems(err: unknown): { path: string; message: string }[] {
  if (err instanceof ApiError && err.status === 422 && typeof err.detail === "object" && err.detail !== null) {
    const errors = (err.detail as { errors?: unknown }).errors;
    if (Array.isArray(errors)) return errors as { path: string; message: string }[];
  }
  return [];
}
