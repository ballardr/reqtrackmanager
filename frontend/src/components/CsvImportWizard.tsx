import { Download, Upload } from "lucide-react";
import Papa from "papaparse";
import { forwardRef, useImperativeHandle, useRef, useState } from "react";

import { api } from "../api/client";
import type { Category, Component, CustomFieldDefinition, ProjectStage } from "../api/types";
import { downloadBlob } from "../utils/download";

type CanonicalField =
  | "name" | "reasoning" | "clarification" | "description"
  | "component_prefix" | "category_prefix" | "level" | "target_version"
  | "owner_email" | "keywords" | "review_date" | "review_lead_days" | "reviewer_email";

const CUSTOM_FIELD_COLUMN_PREFIX = "cf_";

const FIELDS: { key: CanonicalField; label: string; required: boolean; hint: string }[] = [
  { key: "name", label: "Name", required: true, hint: "The requirement's title." },
  {
    key: "component_prefix", label: "Component", required: true,
    hint: "Must exactly match an existing component's prefix (case-sensitive).",
  },
  {
    key: "category_prefix", label: "Category", required: true,
    hint: "Must exactly match an existing category's prefix (case-sensitive).",
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
  const fields = [...FIELDS.map((f) => f.key), ...customFieldKeys];
  const data = [[...FIELDS.map((f) => exampleRow[f.key]), ...customFieldKeys.map(() => "")]];
  return Papa.unparse({ fields, data });
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
  const [exporting, setExporting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

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
  }

  async function confirmImport() {
    const remapped = rows.map((row) => {
      const out: Record<string, string> = {};
      for (const key of mappableKeys) {
        const sourceColumn = mapping[key];
        out[key] = sourceColumn ? row[sourceColumn] ?? "" : "";
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

  const missingRequired = FIELDS.filter((f) => f.required && !mapping[f.key]);

  const fileInput = (
    <input
      ref={fileInputRef}
      type="file"
      accept=".csv,text/csv"
      style={{ display: "none" }}
      disabled={importing}
      onChange={(e) => e.target.files?.[0] && pickFile(e.target.files[0])}
    />
  );

  return (
    <div className="stack" style={{ gap: "0.5rem" }}>
      <div className="row">
        {showImportTrigger ? (
          <label className="btn" style={{ cursor: importing ? "wait" : "pointer" }}>
            <Upload size={16} /> {importing ? "Importing…" : "Import CSV"}
            {fileInput}
          </label>
        ) : (
          fileInput
        )}
        <button
          type="button" className="btn" disabled={exporting}
          onClick={exportCsv}
        >
          <Download size={16} /> {exporting ? "Exporting…" : "Export CSV"}
        </button>
        <button
          type="button" className="btn"
          onClick={() => downloadBlob(
            new Blob([buildTemplateCsv(components, categories, stages, customFields)], { type: "text/csv" }),
            "requirements-import-template.csv"
          )}
        >
          <Download size={16} /> Download template
        </button>
      </div>

      {headers && (
        <div className="card stack">
          <strong>Map your CSV columns</strong>
          <p className="text-muted" style={{ margin: 0 }}>
            Match each field below to a column in your file. Required fields must be mapped before importing.
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
              {FIELDS.map((field) => (
                <tr key={field.key}>
                  <td>
                    {field.label}
                    {field.required && <span style={{ color: "var(--color-danger)" }}> *</span>}
                  </td>
                  <td>
                    <select
                      className="input"
                      value={mapping[field.key] ?? ""}
                      onChange={(e) => setMapping((prev) => ({ ...prev, [field.key]: e.target.value }))}
                    >
                      <option value="">— Not mapped —</option>
                      {headers.map((h) => (
                        <option key={h} value={h}>{h}</option>
                      ))}
                    </select>
                  </td>
                  <td className="text-muted">{field.hint}</td>
                </tr>
              ))}
              {customFields.map((definition) => {
                const key = customFieldColumnKey(definition);
                return (
                  <tr key={key}>
                    <td>{definition.name}{definition.required && <span style={{ color: "var(--color-danger)" }}> *</span>}</td>
                    <td>
                      <select
                        className="input"
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
                          <td key={f.key}>{mapping[f.key] ? row[mapping[f.key]] ?? "" : ""}</td>
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
              Map {missingRequired.map((f) => f.label).join(", ")} before importing.
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
      )}
    </div>
  );
});
