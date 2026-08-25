import { Download, Upload } from "lucide-react";
import Papa from "papaparse";
import { forwardRef, useImperativeHandle, useMemo, useRef, useState } from "react";

import { api } from "../api/client";
import type { Category, Component, CustomFieldDefinition, ProjectStage } from "../api/types";
import { REQUIREMENT_LEVEL_LABEL } from "../api/types";
import { useTerm } from "../context/TerminologyContext";
import { downloadBlob } from "../utils/download";
import { FileUploadTrigger } from "./FileUploadTrigger";
import { Modal } from "./Modal";
import { Popover } from "./Popover";

type CanonicalField =
  | "name" | "reasoning" | "clarification" | "description"
  | "component_prefix" | "category_prefix" | "level" | "target_version"
  | "owner_email" | "keywords" | "review_date" | "review_lead_days" | "reviewer_email";

type FieldDef = { key: CanonicalField; label: string; required: boolean; hint: string };

const CUSTOM_FIELD_COLUMN_PREFIX = "cf_";

/**
 * Fields that can be set to one fixed value applied to every imported row,
 * instead of always being mapped from a CSV column (roadmap item 507 — see
 * docs/ux-audit-2026-08.md "CSV bulk import: no per-field fixed values").
 * Deliberately narrow, matching the audit's own reasoning: component/
 * category/level/target_version are the fields a batch is genuinely likely
 * to share one value across every row (e.g. "this whole CSV is one
 * component, one target version"); name/reasoning/clarification/
 * description are inherently per-row and don't get this toggle — offering
 * it there would just be a confusing way to set the same name/description
 * on every imported requirement. Defaults to column-mapped for every field
 * (today's only behaviour) so existing CSVs/workflows are unaffected.
 *
 * This is a purely client-side concept: the backend import endpoint
 * (`POST .../requirements/import`, `routers/requirements.py`) has no
 * notion of "mapping" at all — it only ever receives a plain canonical CSV
 * (see `confirmImport` below) where every field already has its final
 * per-row value. A fixed value is applied here, before upload, by writing
 * the same value into that field's column for every generated row — the
 * exact same code path a column-mapped field already uses, just with a
 * constant instead of `row[sourceColumn]`. No backend/schema change is
 * needed or was made for this feature; see docs/decisions.md for the
 * verification that confirmed this rather than assuming it.
 */
const FIXED_VALUE_FIELDS = new Set<CanonicalField>(["component_prefix", "category_prefix", "level", "target_version"]);

/**
 * Canonical field order shared by the mapping UI, the CSV preview, and
 * `buildTemplateCsv`'s generated columns — this ordering (and every `key`,
 * the machine-readable CSV column name the backend import/export endpoints
 * expect) is a stable identifier, not display text, so it stays a plain
 * module-level constant. Only `label`/`hint` for `component_prefix`/
 * `category_prefix` are terminology-aware (C-C-03) and built per-render
 * inside the component via `buildFields` below, since a project can rename
 * "component"/"category" — every other field name (Name, Reasoning, Level,
 * ...) isn't one of the six overridable nouns.
 */
function buildFields(componentTerm: string, categoryTerm: string): FieldDef[] {
  const capitalize = (word: string) => word.charAt(0).toUpperCase() + word.slice(1);
  return [
    { key: "name", label: "Name", required: true, hint: "The requirement's title." },
    {
      key: "component_prefix", label: capitalize(componentTerm), required: true,
      hint: `Must exactly match an existing ${componentTerm}'s prefix (case-sensitive).`,
    },
    {
      key: "category_prefix", label: capitalize(categoryTerm), required: true,
      hint: `Must exactly match an existing ${categoryTerm}'s prefix (case-sensitive).`,
    },
    { key: "reasoning", label: "Reasoning", required: false, hint: "Why the requirement exists." },
    { key: "clarification", label: "Clarification", required: false, hint: "Additional scope notes." },
    { key: "description", label: "Description", required: false, hint: "Further elaboration." },
    {
      key: "level", label: "Level", required: false,
      hint: '"requirement" or "recommended" — defaults to "requirement" if left blank.',
    },
    {
      key: "target_version", label: "Target version", required: false,
      hint: "Must exactly match an existing stage's name, if set.",
    },
    { key: "owner_email", label: "Owner email", required: false, hint: "Must match an existing user's email, if set." },
    { key: "keywords", label: "Keywords", required: false, hint: "Semicolon-separated, e.g. \"safety;power\"." },
    { key: "review_date", label: "Review date", required: false, hint: "YYYY-MM-DD, if set." },
    { key: "review_lead_days", label: "Review lead days", required: false, hint: "Whole number of days, if set." },
    { key: "reviewer_email", label: "Reviewer email", required: false, hint: "Must match an existing user's email, if set." },
  ];
}

const PREVIEW_ROWS = 5;

function customFieldColumnKey(definition: CustomFieldDefinition): string {
  return `${CUSTOM_FIELD_COLUMN_PREFIX}${definition.name}`;
}

function guessMapping(headers: string[], keys: string[]): Record<string, string> {
  const mapping: Record<string, string> = {};
  for (const key of keys) {
    const match = headers.find((h) => h.trim().toLowerCase() === key.toLowerCase()) ??
      headers.find((h) => h.trim().toLowerCase().replace(/[\s_-]/g, "") === key.replace(/_/g, "").toLowerCase());
    mapping[key] = match ?? "";
  }
  return mapping;
}

function buildTemplateCsv(
  fields: FieldDef[],
  components: Component[], categories: Category[], stages: ProjectStage[], customFields: CustomFieldDefinition[]
): string {
  // A category belonging to the example component specifically — the tree
  // means the first category overall isn't necessarily one of this
  // component's own, which would produce an inconsistent (though still
  // server-validated) example row.
  const exampleCategory = categories.find((c) => c.component_id === components[0]?.id);
  const exampleRow: Record<CanonicalField, string> = {
    name: "Example requirement name",
    component_prefix: components[0]?.prefix ?? "SW",
    category_prefix: exampleCategory?.prefix ?? "PERF",
    reasoning: "Why this requirement exists",
    clarification: "",
    description: "",
    level: "requirement",
    target_version: stages[0]?.name ?? "",
    owner_email: "",
    keywords: "",
    review_date: "",
    review_lead_days: "",
    reviewer_email: "",
  };
  const customFieldKeys = customFields.map(customFieldColumnKey);
  const columnKeys = [...fields.map((f) => f.key), ...customFieldKeys];
  const data = [[...fields.map((f) => exampleRow[f.key]), ...customFieldKeys.map(() => "")]];
  return Papa.unparse({ fields: columnKeys, data });
}

/** Imperative handle so a caller-supplied "Import from CSV" trigger
 * elsewhere on the page (see `showImportTrigger`) can open this
 * component's own file picker without either component needing to know
 * about the other's internal state. */
export interface CsvImportWizardHandle {
  openFilePicker: () => void;
}

/**
 * Full-fidelity CSV bulk-import/export for requirements: import parses the
 * file client-side (Papaparse) so the user can map their own column headers
 * onto the backend's fixed field names (plus one `cf_<name>` column per the
 * project's custom field definitions) before anything is uploaded, rather
 * than requiring the CSV to already use those exact names. The backend
 * endpoints (`POST`/`GET .../requirements/import`/`/export`, see
 * `routers/requirements.py`) are unchanged by this remapping — it only
 * builds a canonically-headed CSV client-side and sends that instead of the
 * user's original file. Export downloads the server-generated file as-is
 * (it's already canonically headed and directly re-importable).
 *
 * Once a file is picked, the column-mapping/preview step (everything past
 * the trigger row) opens in a `Modal` (`size="lg"`, roadmap item 506) —
 * previously an always-inline `<div className="card stack">` block. This
 * is a container move only; the mapping/preview logic and both backend
 * endpoints are otherwise unchanged. `component_prefix`/`category_prefix`/
 * `level`/`target_version` additionally support a per-field "same value for
 * every row" toggle (roadmap item 507, `FIXED_VALUE_FIELDS` above) —
 * `name`/`reasoning`/`clarification`/`description` stay column-only, since
 * a batch import is never uniform on those.
 */
export const CsvImportWizard = forwardRef<CsvImportWizardHandle, {
  projectId: string;
  projectName: string;
  components: Component[];
  categories: Category[];
  stages: ProjectStage[];
  customFields: CustomFieldDefinition[];
  importing: boolean;
  onImport: (file: File) => Promise<void>;
  /** Style guide "Pattern: create panels, popovers, and one door for
   * bulk" — `RequirementsPage` renders its own single "+ Add requirement"
   * split trigger (Add one / Import from CSV) instead of this component's
   * own always-visible "Import CSV" button competing with it. Defaults to
   * true so any other future caller gets the previous, self-contained
   * behaviour without having to opt in. Export/template stay visible
   * either way — they're downloads, not part of the create flow this
   * pattern is about. */
  showImportTrigger?: boolean;
}>(function CsvImportWizard(
  { projectId, projectName, components, categories, stages, customFields, importing, onImport, showImportTrigger = true },
  ref
) {
  const [headers, setHeaders] = useState<string[] | null>(null);
  const [rows, setRows] = useState<Record<string, string>[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  // "Same value for every row" toggle state, keyed by `CanonicalField` —
  // only ever set for keys in `FIXED_VALUE_FIELDS`, see that constant's own
  // doc comment above. `fixedMode[key]` true means `fixedValues[key]`
  // (not `mapping[key]`) is this field's source of truth for every row.
  const [fixedMode, setFixedMode] = useState<Partial<Record<CanonicalField, boolean>>>({});
  const [fixedValues, setFixedValues] = useState<Partial<Record<CanonicalField, string>>>({});
  const [exporting, setExporting] = useState(false);
  const [exportMenuOpen, setExportMenuOpen] = useState(false);
  const exportTriggerRef = useRef<HTMLButtonElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const componentTerm = useTerm("component");
  const categoryTerm = useTerm("category");
  const FIELDS = useMemo(() => buildFields(componentTerm, categoryTerm), [componentTerm, categoryTerm]);

  useImperativeHandle(ref, () => ({
    openFilePicker: () => fileInputRef.current?.click(),
  }));

  const mappableKeys = [...FIELDS.map((f) => f.key), ...customFields.map(customFieldColumnKey)];

  function pickFile(file: File) {
    Papa.parse<Record<string, string>>(file, {
      header: true,
      skipEmptyLines: true,
      complete: (results) => {
        const detectedHeaders = results.meta.fields ?? [];
        setHeaders(detectedHeaders);
        setRows(results.data);
        setMapping(guessMapping(detectedHeaders, mappableKeys));
      },
    });
  }

  function cancel() {
    setHeaders(null);
    setRows([]);
    setMapping({});
    setFixedMode({});
    setFixedValues({});
  }

  /** The value every row should get for `key`, per the field's own toggle
   * state — a fixed constant if `fixedMode[key]` is set, otherwise the
   * mapped source column's cell for that row (unchanged from before this
   * feature). Shared by `confirmImport` (building the real upload) and the
   * preview table below, so the two can never show a different resolution
   * of the same toggle state. */
  function resolveFieldValue(key: string, row: Record<string, string>): string {
    if (FIXED_VALUE_FIELDS.has(key as CanonicalField) && fixedMode[key as CanonicalField]) {
      return fixedValues[key as CanonicalField] ?? "";
    }
    const sourceColumn = mapping[key];
    return sourceColumn ? row[sourceColumn] ?? "" : "";
  }

  async function confirmImport() {
    const remapped = rows.map((row) => {
      const out: Record<string, string> = {};
      for (const key of mappableKeys) {
        out[key] = resolveFieldValue(key, row);
      }
      return out;
    });
    const csvText = Papa.unparse({ fields: mappableKeys, data: remapped });
    const file = new File([csvText], "import.csv", { type: "text/csv" });
    await onImport(file);
    cancel();
  }

  async function exportCsv() {
    setExporting(true);
    try {
      const blob = await api.getForBlob(`/api/v1/projects/${projectId}/requirements/export`);
      const safeName = projectName.replace(/[\\/"\r\n\t]/g, "") || "project";
      downloadBlob(blob, `${safeName}-requirements-export.csv`);
    } finally {
      setExporting(false);
    }
  }

  // A required field is satisfied either by a column mapping or, if its
  // "same value for every row" toggle is on, by a non-empty fixed value —
  // level/target_version are never required, so only component/category
  // ever reach the fixed-value branch here.
  const missingRequired = FIELDS.filter((f) =>
    f.required && (FIXED_VALUE_FIELDS.has(f.key) && fixedMode[f.key] ? !fixedValues[f.key] : !mapping[f.key])
  );

  /** The fixed-value replacement for a `FIXED_VALUE_FIELDS` column-mapping
   * `<select>`, once that field's toggle is on. Deliberately a `<select>`
   * sourced from the project's real components/categories/stages (not a
   * free-text input) for component/category/target_version — the same
   * values a mapped column would eventually need to match exactly on the
   * backend, so picking from a list can't produce an unknown-prefix/
   * unknown-stage row error the way a typo in free text could. `level`
   * already needs a `<select>` (it's an enum) — rendered through
   * `REQUIREMENT_LEVEL_LABEL` per style guide Principle 12, matching the
   * per-row create form's own level select on `RequirementsPage.tsx`. */
  function renderFixedValueInput(field: FieldDef) {
    const value = fixedValues[field.key] ?? "";
    const setValue = (v: string) => setFixedValues((prev) => ({ ...prev, [field.key]: v }));

    if (field.key === "level") {
      return (
        <select
          className="input" aria-label={`Fixed ${field.label.toLowerCase()}`}
          value={value || "requirement"} onChange={(e) => setValue(e.target.value)}
        >
          <option value="requirement">{REQUIREMENT_LEVEL_LABEL.requirement}</option>
          <option value="recommended">{REQUIREMENT_LEVEL_LABEL.recommended}</option>
          <option value="optional">{REQUIREMENT_LEVEL_LABEL.optional}</option>
        </select>
      );
    }
    if (field.key === "target_version") {
      return (
        <select className="input" aria-label={`Fixed ${field.label.toLowerCase()}`} value={value} onChange={(e) => setValue(e.target.value)}>
          <option value="">— Project's default stage —</option>
          {stages.map((s) => (
            <option key={s.id} value={s.name}>{s.name}</option>
          ))}
        </select>
      );
    }
    if (field.key === "component_prefix") {
      return (
        <select className="input" aria-label={`Fixed ${field.label.toLowerCase()}`} value={value} onChange={(e) => setValue(e.target.value)}>
          <option value="">— Choose —</option>
          {components.map((c) => (
            <option key={c.id} value={c.prefix}>{c.name} ({c.prefix})</option>
          ))}
        </select>
      );
    }
    // category_prefix: filtered to the fixed component's own categories
    // once a component is also fixed (a category belongs to exactly one
    // component under the tree, C-C-XX) — otherwise every category is
    // offered, with its own component name prefixed so same-named
    // categories under different components stay distinguishable.
    const fixedComponentPrefix = fixedMode.component_prefix ? fixedValues.component_prefix : undefined;
    const fixedComponent = fixedComponentPrefix ? components.find((c) => c.prefix === fixedComponentPrefix) : undefined;
    const categoryOptions = fixedComponent ? categories.filter((c) => c.component_id === fixedComponent.id) : categories;
    return (
      <select className="input" aria-label={`Fixed ${field.label.toLowerCase()}`} value={value} onChange={(e) => setValue(e.target.value)}>
        <option value="">— Choose —</option>
        {categoryOptions.map((c) => {
          const owner = components.find((comp) => comp.id === c.component_id);
          return (
            <option key={c.id} value={c.prefix}>
              {fixedComponent ? "" : owner ? `${owner.name} / ` : ""}{c.name} ({c.prefix})
            </option>
          );
        })}
      </select>
    );
  }

  return (
    <div className="stack" style={{ gap: "0.5rem" }}>
      <div className="row">
        <FileUploadTrigger
          ref={fileInputRef}
          accept=".csv,text/csv"
          disabled={importing}
          showTrigger={showImportTrigger}
          onSelect={pickFile}
        >
          <Upload size={16} /> {importing ? "Importing…" : "Import CSV"}
        </FileUploadTrigger>
        <button
          ref={exportTriggerRef}
          type="button" className="btn"
          onClick={() => setExportMenuOpen((v) => !v)}
        >
          <Download size={16} /> {exporting ? "Exporting…" : "Export"}
        </button>
        {exportMenuOpen && (
          <Popover anchorRef={exportTriggerRef} title="Export" onClose={() => setExportMenuOpen(false)}>
            <div className="stack" style={{ gap: "0.25rem", minWidth: 180 }}>
              <button
                type="button" className="btn" style={{ justifyContent: "flex-start" }} disabled={exporting}
                onClick={() => {
                  setExportMenuOpen(false);
                  exportCsv();
                }}
              >
                <Download size={14} /> {exporting ? "Exporting…" : "Export CSV"}
              </button>
              <button
                type="button" className="btn" style={{ justifyContent: "flex-start" }}
                onClick={() => {
                  setExportMenuOpen(false);
                  downloadBlob(
                    new Blob([buildTemplateCsv(FIELDS, components, categories, stages, customFields)], { type: "text/csv" }),
                    "requirements-import-template.csv"
                  );
                }}
              >
                <Download size={14} /> Download template
              </button>
            </div>
          </Popover>
        )}
      </div>

      {headers && (
        <Modal title="Map your CSV columns" onClose={cancel} size="lg">
          <div className="stack">
          <p className="text-muted" style={{ margin: 0 }}>
            Match each field below to a column in your file, or set one fixed value for every row. Required fields
            must be set before importing.
          </p>
          <table>
            <thead>
              <tr>
                <th>Field</th>
                <th>Your column</th>
                <th>What it's for</th>
              </tr>
            </thead>
            <tbody>
              {FIELDS.map((field) => {
                const canFixValue = FIXED_VALUE_FIELDS.has(field.key);
                return (
                  <tr key={field.key}>
                    <td>
                      {field.label}
                      {field.required && <span style={{ color: "var(--color-danger)" }}> *</span>}
                    </td>
                    <td>
                      {canFixValue && (
                        <label className="row" style={{ gap: "0.35rem", alignItems: "center", marginBottom: "0.25rem" }}>
                          <input
                            type="checkbox"
                            checked={fixedMode[field.key] ?? false}
                            // Every field with this toggle shares the same
                            // visible text ("Same value for every row"), so
                            // an explicit per-field `aria-label` (which wins
                            // over the wrapping <label>'s own text for
                            // accessible-name computation) keeps the four
                            // checkboxes distinguishable to a screen reader
                            // and to `getByLabelText` in tests, rather than
                            // four controls sharing one ambiguous name.
                            aria-label={`Use the same ${field.label.toLowerCase()} for every row`}
                            onChange={(e) => setFixedMode((prev) => ({ ...prev, [field.key]: e.target.checked }))}
                          />
                          <span className="text-muted">Same value for every row</span>
                        </label>
                      )}
                      {canFixValue && fixedMode[field.key] ? (
                        renderFixedValueInput(field)
                      ) : (
                        <select
                          className="input"
                          aria-label={`Map ${field.label}`}
                          value={mapping[field.key] ?? ""}
                          onChange={(e) => setMapping((prev) => ({ ...prev, [field.key]: e.target.value }))}
                        >
                          <option value="">— Not mapped —</option>
                          {headers.map((h) => (
                            <option key={h} value={h}>{h}</option>
                          ))}
                        </select>
                      )}
                    </td>
                    <td className="text-muted">{field.hint}</td>
                  </tr>
                );
              })}
              {customFields.map((definition) => {
                const key = customFieldColumnKey(definition);
                return (
                  <tr key={key}>
                    <td>{definition.name}{definition.required && <span style={{ color: "var(--color-danger)" }}> *</span>}</td>
                    <td>
                      <select
                        className="input"
                        aria-label={`Map ${definition.name}`}
                        value={mapping[key] ?? ""}
                        onChange={(e) => setMapping((prev) => ({ ...prev, [key]: e.target.value }))}
                      >
                        <option value="">— Not mapped —</option>
                        {headers.map((h) => (
                          <option key={h} value={h}>{h}</option>
                        ))}
                      </select>
                    </td>
                    <td className="text-muted">Custom field ({definition.field_type}).</td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {rows.length > 0 && (
            <div className="stack" style={{ gap: "0.25rem" }}>
              <strong>Preview (first {Math.min(PREVIEW_ROWS, rows.length)} of {rows.length} rows)</strong>
              <div style={{ overflowX: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      {FIELDS.map((f) => <th key={f.key}>{f.label}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.slice(0, PREVIEW_ROWS).map((row, i) => (
                      <tr key={i}>
                        {FIELDS.map((f) => (
                          <td key={f.key}>{resolveFieldValue(f.key, row)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {missingRequired.length > 0 && (
            <p style={{ color: "var(--color-danger)", margin: 0 }}>
              {missingRequired.map((f) => f.label).join(", ")} still need a column or fixed value before importing.
            </p>
          )}

          <div className="row">
            <button
              className="btn btn-primary" disabled={missingRequired.length > 0 || importing}
              onClick={confirmImport}
            >
              {importing ? "Importing…" : `Import ${rows.length} row(s)`}
            </button>
            <button className="btn" onClick={cancel} disabled={importing}>Cancel</button>
          </div>
          </div>
        </Modal>
      )}
    </div>
  );
});
