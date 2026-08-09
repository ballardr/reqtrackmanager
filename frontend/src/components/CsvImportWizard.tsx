import { Download, Upload } from "lucide-react";
import Papa from "papaparse";
import { useState } from "react";

import type { Category, Component, ProjectStage } from "../api/types";

type CanonicalField = "name" | "reasoning" | "component_prefix" | "category_prefix" | "level" | "target_version";

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
  {
    key: "level", label: "Level", required: false,
    hint: '"requirement" or "recommended" — defaults to "requirement" if left blank.',
  },
  {
    key: "target_version", label: "Target version", required: false,
    hint: "Must exactly match an existing stage's name, if set.",
  },
];

const PREVIEW_ROWS = 5;

function guessMapping(headers: string[]): Record<CanonicalField, string> {
  const mapping = {} as Record<CanonicalField, string>;
  for (const field of FIELDS) {
    const match = headers.find((h) => h.trim().toLowerCase() === field.key) ??
      headers.find((h) => h.trim().toLowerCase().replace(/[\s_-]/g, "") === field.key.replace(/_/g, ""));
    mapping[field.key] = match ?? "";
  }
  return mapping;
}

function buildTemplateCsv(components: Component[], categories: Category[], stages: ProjectStage[]): string {
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
    level: "requirement",
    target_version: stages[0]?.name ?? "",
  };
  return Papa.unparse({
    fields: FIELDS.map((f) => f.key),
    data: [FIELDS.map((f) => exampleRow[f.key])],
  });
}

function downloadCsv(filename: string, content: string) {
  const blob = new Blob([content], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  // See ReportsPage.tsx's downloadBlob: the anchor must be attached to the
  // document for `download` (and its filename/suffix) to reliably apply.
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/**
 * CSV bulk-import for requirements: parses the file client-side (Papaparse)
 * so the user can map their own column headers onto the backend's fixed
 * field names before anything is uploaded, rather than requiring the CSV
 * to already use those exact names. The backend endpoint
 * (`POST /projects/{id}/requirements/import`, see `routers/requirements.py`)
 * is unchanged — this only builds a canonically-headed CSV client-side and
 * sends that instead of the user's original file.
 */
export function CsvImportWizard({
  components, categories, stages, importing, onImport,
}: {
  components: Component[];
  categories: Category[];
  stages: ProjectStage[];
  importing: boolean;
  onImport: (file: File) => Promise<void>;
}) {
  const [headers, setHeaders] = useState<string[] | null>(null);
  const [rows, setRows] = useState<Record<string, string>[]>([]);
  const [mapping, setMapping] = useState<Record<CanonicalField, string>>({} as Record<CanonicalField, string>);

  function pickFile(file: File) {
    Papa.parse<Record<string, string>>(file, {
      header: true,
      skipEmptyLines: true,
      complete: (results) => {
        const detectedHeaders = results.meta.fields ?? [];
        setHeaders(detectedHeaders);
        setRows(results.data);
        setMapping(guessMapping(detectedHeaders));
      },
    });
  }

  function cancel() {
    setHeaders(null);
    setRows([]);
    setMapping({} as Record<CanonicalField, string>);
  }

  async function confirmImport() {
    const canonicalHeaders = FIELDS.map((f) => f.key);
    const remapped = rows.map((row) => {
      const out: Record<string, string> = {};
      for (const field of FIELDS) {
        const sourceColumn = mapping[field.key];
        out[field.key] = sourceColumn ? row[sourceColumn] ?? "" : "";
      }
      return out;
    });
    const csvText = Papa.unparse({ fields: canonicalHeaders, data: remapped });
    const file = new File([csvText], "import.csv", { type: "text/csv" });
    await onImport(file);
    cancel();
  }

  const missingRequired = FIELDS.filter((f) => f.required && !mapping[f.key]);

  return (
    <div className="stack" style={{ gap: "0.5rem" }}>
      <div className="row">
        <label className="btn" style={{ cursor: importing ? "wait" : "pointer" }}>
          <Upload size={16} /> {importing ? "Importing…" : "Import CSV"}
          <input
            type="file"
            accept=".csv,text/csv"
            style={{ display: "none" }}
            disabled={importing}
            onChange={(e) => e.target.files?.[0] && pickFile(e.target.files[0])}
          />
        </label>
        <button
          type="button" className="btn"
          onClick={() => downloadCsv("requirements-import-template.csv", buildTemplateCsv(components, categories, stages))}
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
}
