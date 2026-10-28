/**
 * Module: testing/reportLayoutFixtures
 *
 * Storybook-only builders for the report layout designer: layouts, versions, the field and widget catalogues and
 * a fake `ReportLayoutApi` whose methods are `fn()` spies. The fake keeps its layouts in memory, so a story can
 * save, rename or hide and read the change back, and it parses the text with a tiny stand-in for the server:
 * text containing the word `BROKEN` yields one positioned error, anything else is valid. The real parser is the
 * server's and is covered by the backend tests.
 */
import { fn } from "storybook/test";

import type {
  BlockCatalogue, BlockField, BlockType, PreviewResult, ReportFieldCatalogue, TreeCheck, TreeProblem, ReportLayoutApi, ReportLayoutDetail, ReportLayoutSummary, ReportLayoutTree,
  ReportLayoutVersion, ReportWidget, TextParseResult,
} from "../api/reportLayouts";

/** Longest the designer takes to finish checking text after typing stops, for a story to wait on. */
export const TEXT_CHECKED_MS = 3000;

export const LAYOUT_TEXT = `@layout document

@heading Requirements of {{project_name}}

@each requirement sort title as req
  @heading level=2 {{req.code}} {{req.title}}
@end
`;

/** A layout summary (own, editable, document). */
export function buildLayoutSummary(overrides: Partial<ReportLayoutSummary> = {}): ReportLayoutSummary {
  return {
    id: "layout-1", organization_id: "org-1", project_id: "project-1", name: "Requirements by component",
    description: "Every requirement with its component.", folder: "", family: "document", current_version: 2, origin: "project",
    hidden: false, editable: true, updated_at: "2026-10-20T09:30:00Z", ...overrides,
  };
}

/** A tree standing for `text` (the fake server keeps the text inside it so format can give it back). */
export function treeOf(text: string, family: "document" | "table" = "document"): ReportLayoutTree {
  return { schema_version: 1, family, nodes: [], source_text: text };
}

/** One saved version. */
export function buildLayoutVersion(version: number, text = LAYOUT_TEXT, overrides: Partial<ReportLayoutVersion> = {}): ReportLayoutVersion {
  return {
    version, schema_version: 1, tree: treeOf(text), tree_hash: `hash-${version}`, comment: `Change ${version}`, created_by: "user-1",
    created_at: `2026-10-${10 + version}T09:00:00Z`, ...overrides,
  };
}

/** A layout with its current version. */
export function buildLayoutDetail(overrides: Partial<ReportLayoutDetail> = {}, text = LAYOUT_TEXT): ReportLayoutDetail {
  const summary = buildLayoutSummary(overrides);
  return { ...summary, current: buildLayoutVersion(summary.current_version, text), ...overrides };
}

/** The record types a stand-in project can use. */
export function buildFieldCatalogue(): ReportFieldCatalogue {
  return {
    types: [
      {
        type: "pain_point", label: "Pain point",
        fields: [
          { key: "code", label: "Code", kind: "text", reserved: true, choices: [] },
          { key: "title", label: "Title", kind: "text", reserved: true, choices: [] },
          { key: "severity", label: "Severity", kind: "number", reserved: false, choices: [] },
        ],
      },
      {
        type: "requirement", label: "Requirement",
        fields: [
          { key: "code", label: "Code", kind: "text", reserved: true, choices: [] },
          { key: "title", label: "Title", kind: "text", reserved: true, choices: [] },
          { key: "status", label: "Status", kind: "enum", reserved: true, choices: ["Draft", "Approved"] },
          { key: "description", label: "Description", kind: "text", reserved: false, choices: [], math: true },
        ],
      },
    ],
    placeholders: ["project_name", "report_title", "generated_on", "organisation"],
    group_fields: { value: "text", count: "number" },
    schema_version: 1,
  };
}

const field = (key: string, label: string, kind: string, extra: Partial<BlockField> = {}): BlockField => ({
  key, label, kind, required: false, help: `About ${label.toLowerCase()}.`, max_length: null, minimum: null, maximum: null, default: null,
  choices: [], features: [], depends_on: null, families: [], ...extra,
});

const source = field("source", "Records", "source", { required: true });
const block = (type: string, label: string, template: Record<string, unknown>, extra: Partial<BlockType> = {}): BlockType => ({
  type, label, description: `${label}.`, families: ["document"], fields: [], containers: [], provides: null, template, described: true, ...extra,
});

/** The block catalogue the server publishes (the ten core blocks), for stories of the outline. */
export function buildBlockCatalogue(): BlockCatalogue {
  return {
    blocks: [
      block("heading", "Heading", { type: "heading", text: "Heading", level: 2 }, {
        fields: [field("text", "Heading", "text", { required: true, max_length: 500, features: ["placeholders"] }), field("level", "Level", "integer", { minimum: 1, maximum: 4, default: 1 })],
      }),
      block("text", "Text", { type: "text", text: "Some text." }, {
        fields: [field("text", "Text", "longtext", { required: true, features: ["placeholders", "markdown"] })],
      }),
      block("page_break", "Page break", { type: "page_break" }),
      block("equation", "Equation", { type: "equation", tex: "a = b" }, { fields: [field("tex", "TeX", "tex", { required: true })] }),
      block("table", "Table", { type: "table", source: {}, columns: [] }, {
        fields: [source, field("columns", "Columns", "columns", { required: true }), field("empty_text", "Text when there is nothing", "text")],
      }),
      block("each", "For each record", { type: "each", source: {}, children: [] }, {
        fields: [source, field("as", "Name", "alias", { default: "record" }), field("empty_text", "Text when there is nothing", "text")],
        containers: [{ key: "children", label: "Contents" }], provides: { key: "as", kind: "record", default: "record" },
      }),
      block("group", "Group records", { type: "group", source: {}, by: "", children: [] }, {
        fields: [source, field("by", "Group by", "record_field", { required: true, depends_on: "source" }), field("as", "Name", "alias", { default: "group" })],
        containers: [{ key: "children", label: "Contents" }], provides: { key: "as", kind: "group", default: "group" },
      }),
      block("if", "If", { type: "if", when: {}, children: [] }, {
        fields: [field("when", "Condition", "condition", { required: true })],
        containers: [{ key: "children", label: "Contents" }, { key: "else_children", label: "Otherwise" }],
      }),
      block("widget", "Report component", { type: "widget", key: "" }, {
        fields: [
          field("key", "Component", "widget_key", { required: true }), field("params", "Settings", "widget_params", { depends_on: "key" }),
          field("sort", "Sort", "widget_sort", { depends_on: "key" }), field("empty_text", "Text when there is nothing", "text"),
        ],
      }),
      block("sheet", "Sheet", { type: "sheet", name: "Sheet", source: {}, columns: [] }, {
        families: ["table"],
        fields: [
          field("name", "Sheet name", "text", { required: true, max_length: 31 }), source, field("as", "Name", "alias", { default: "record" }),
          field("joins", "Joins", "joins"), field("columns", "Columns", "columns", { required: true }),
        ],
        provides: { key: "as", kind: "record", default: "record" },
      }),
    ],
    layout_fields: [
      field("orientation", "Page orientation", "choice", { choices: ["portrait", "landscape"], default: "portrait", families: ["document"] }),
      field("variables", "Variables", "variables"),
    ],
    field_kinds: ["text", "longtext", "integer", "boolean", "choice", "tex", "alias", "record_field", "source", "columns", "joins", "condition", "widget_key", "widget_params", "widget_sort", "variables"],
    operators: {
      text: ["eq", "ne", "contains", "in", "not_in", "empty", "not_empty"],
      enum: ["eq", "ne", "in", "not_in", "empty", "not_empty"],
      number: ["eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "empty", "not_empty"],
    },
    valueless_operators: ["empty", "not_empty"],
    list_operators: ["in", "not_in"],
    schema_version: 1,
  };
}

/** A real tree of a small document (a heading, then a For each with a heading and a table inside). */
export function buildOutlineTree(): ReportLayoutTree {
  return {
    schema_version: 1, family: "document", orientation: "portrait",
    nodes: [
      { type: "heading", text: "Requirements of {{project_name}}", level: 1 },
      {
        type: "each", source: { record_type: "requirement", sort: [{ field: "title" }] }, as: "req",
        children: [
          { type: "heading", text: "{{req.code}} {{req.title}}", level: 2 },
          { type: "table", source: { record_type: "pain_point", linked_from: "req" }, columns: [{ field: "code" }, { field: "title", label: "Pain point" }] },
        ],
      },
    ],
  };
}

/** The stand-in checker: empty text or a missing record type is a problem at that path; anything else is fine. */
export function fakeValidate(tree: ReportLayoutTree): TreeCheck {
  const errors: TreeProblem[] = [];
  const walk = (nodes: unknown, prefix: string) => {
    if (!Array.isArray(nodes)) return;
    nodes.forEach((raw, i) => {
      const node = raw as Record<string, unknown>;
      const here = `${prefix}[${i}]`;
      if ((node.type === "heading" || node.type === "text") && String(node.text ?? "").trim() === "") errors.push({ path: `${here}.text`, message: "Must not be empty." });
      const src = node.source as Record<string, unknown> | undefined;
      if (src && !src.record_type && !src.group) errors.push({ path: `${here}.source.record_type`, message: "Must be a reportable record type: pain_point, requirement." });
      walk(node.children, `${here}.children`);
      walk(node.else_children, `${here}.else_children`);
    });
  };
  walk(tree.nodes, "nodes");
  return { ok: errors.length === 0, errors, node_count: 0 };
}

/** Two report parts: a table with a setting, and figures. */
export function buildWidgets(): ReportWidget[] {
  return [
    {
      key: "risk_management.risk-register.register", title: "Risk register", description: "Every risk with its rating.", kind: "section",
      report_title: "Risk register", module_key: "risk_management", module_name: "Risk Management",
      params: [
        { name: "min_rating", type: "integer", default: 1, choices: null, minimum: 1, maximum: 25, description: "Lowest rating to list.", label: "Lowest rating" },
        { name: "owner", type: "string", default: null, choices: null, minimum: null, maximum: null, description: "Only this owner.", label: "Owner" },
      ],
    },
    {
      key: "risk_management.risk-register.figures", title: "Headline figures", description: "", kind: "figures",
      report_title: "Risk register", module_key: "risk_management", module_name: "Risk Management", params: [],
    },
    {
      key: "decisions.decision-register.register", title: "Decision register", description: "Every Decision.", kind: "section",
      report_title: "Decision register", module_key: "decisions", module_name: "Decision Management", params: [],
    },
    {
      key: "decisions.approval-ageing.ageing", title: "Approval ageing", description: "", kind: "section",
      report_title: "Approval ageing", module_key: "decisions", module_name: "Decision Management", params: [],
    },
    {
      key: "decisions.decision-log.log", title: "Decision log", description: "", kind: "section",
      report_title: "Decision log", module_key: "decisions", module_name: "Decision Management", params: [],
    },
  ];
}

/** A successful document preview. */
export function buildDocumentPreview(overrides: Partial<PreviewResult> = {}): PreviewResult {
  return {
    ok: true, errors: [], family: "document", warnings: [], records_read: 3, duration_ms: 12, projects: 1, sheets: [],
    html: "<!doctype html><html><body><h1>Requirements of Atlas</h1><p>REQ-001 Brake pads</p></body></html>", ...overrides,
  };
}

/** A successful table preview whose only sheet was capped. */
export function buildSheetPreview(): PreviewResult {
  return {
    ok: true, errors: [], family: "table", html: null, warnings: [], records_read: 250, duration_ms: 30, projects: 2,
    sheets: [{ name: "Requirements", columns: ["Code", "Title"], rows: [["REQ-001", "Brake pads"], ["REQ-002", "Handbrake"]], total_rows: 250 }],
  };
}

/** The stand-in parser: `BROKEN` anywhere is one syntax error on its line, else the text is the tree. */
export function fakeParse(text: string): TextParseResult {
  const lines = text.split("\n");
  const index = lines.findIndex((line) => line.includes("BROKEN"));
  if (index >= 0) return { ok: false, tree: null, errors: [{ line: index + 1, column: lines[index].indexOf("BROKEN") + 1, message: "Unknown word BROKEN." }] };
  return { ok: true, tree: treeOf(text, text.startsWith("@layout table") ? "table" : "document"), errors: [] };
}

/**
 * An in-memory `ReportLayoutApi`. `layouts` are the scope's layouts (the first is opened by `get`).
 *
 * `stateful: false` makes every write answer as if it worked without remembering it, for stories whose api is
 * shared by every replay of every story in a file (the designer's): a saved version, a rename or a delete then
 * never changes what the next story reads. The list panel's stories keep the default so a hidden layout really
 * leaves the list.
 */
export function buildLayoutApi(
  layouts: ReportLayoutSummary[] = [buildLayoutSummary()],
  overrides: Partial<ReportLayoutApi> & { kind?: "project" | "organization"; stateful?: boolean } = {},
): ReportLayoutApi {
  const stateful = overrides.stateful !== false;
  const store = layouts.map((layout) => ({ ...layout }));
  const kind = overrides.kind ?? "project";
  const fake: ReportLayoutApi = {
    scope: { kind, id: kind === "project" ? "project-1" : "org-1" },
    list: fn(async () => store.map((layout) => ({ ...layout }))),
    create: fn(async (body) => {
      const created = buildLayoutSummary({
        id: `layout-${store.length + 1}`, name: body.name, description: body.description, folder: body.folder ?? "", family: body.family, current_version: 1,
      });
      store.push(created);
      return { ...created, current: { ...buildLayoutVersion(1), tree: body.tree } };
    }),
    get: fn(async (id: string) => {
      const found = store.find((layout) => layout.id === id) ?? store[0];
      return { ...found, current: buildLayoutVersion(found.current_version, LAYOUT_TEXT) };
    }),
    versions: fn(async () => [
      { version: 2, tree_hash: "h2", comment: "Added the heading", created_by: "user-1", created_at: "2026-10-12T09:00:00Z" },
      { version: 1, tree_hash: "h1", comment: "First draft", created_by: "user-1", created_at: "2026-10-11T09:00:00Z" },
    ]),
    version: fn(async (_id: string, version: number) => buildLayoutVersion(version, version === 1 ? "@layout document\n\n@heading Draft\n" : LAYOUT_TEXT)),
    save: fn(async (id: string, body: { tree: ReportLayoutTree; base_version: number }) => {
      const found = store.find((layout) => layout.id === id) ?? store[0];
      const next = body.base_version + 1;
      if (stateful) found.current_version = next;
      return { ...found, current_version: next, current: { ...buildLayoutVersion(next), tree: body.tree } };
    }),
    update: fn(async (id: string, body: { name?: string; description?: string; folder?: string }) => {
      const found = store.find((layout) => layout.id === id) ?? store[0];
      if (stateful) Object.assign(found, body);
      return { ...found, ...body };
    }),
    remove: fn(async (id: string) => {
      const at = store.findIndex((layout) => layout.id === id);
      if (stateful && at >= 0) store.splice(at, 1);
    }),
    parseText: fn(async (text: string) => fakeParse(text)),
    formatTree: fn(async (tree: ReportLayoutTree) => String(tree.source_text ?? `@layout ${String(tree.family)}\n`)),
    fields: fn(async () => buildFieldCatalogue()),
    widgets: fn(async () => buildWidgets()),
    blocks: fn(async () => buildBlockCatalogue()),
    validate: fn(async (tree: ReportLayoutTree) => fakeValidate(tree)),
    preview: fn(async () => buildDocumentPreview()),
    draftVariables: fn(async () => ({ ok: true, variables: [], errors: [] })),
  };
  if (kind === "organization") {
    fake.addStarters = fn(async () => []);
  }
  if (kind === "project") {
    fake.setHidden = fn(async (id: string, hidden: boolean) => {
      const found = store.find((layout) => layout.id === id) ?? store[0];
      found.hidden = hidden;
      return { ...found };
    });
    fake.restore = fn(async (ids: string[]) => {
      for (const layout of store) if (ids.includes(layout.id)) layout.hidden = false;
    });
  }
  const { kind: _kind, stateful: _stateful, ...rest } = overrides;
  void _kind;
  void _stateful;
  return { ...fake, ...rest };
}
