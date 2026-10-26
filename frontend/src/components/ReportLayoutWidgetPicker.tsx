/**
 * Module: components/ReportLayoutWidgetPicker
 *
 * The designer's widget picker: lists the report parts a `[[widget.key ...]]` line can embed, grouped by the
 * module and report they come from, lets the author set the report's parameters with the same form the Reports
 * page uses (`ReportParamsForm`) and inserts the finished line.
 *
 * Responsibilities: filter by title or report, show what the line will read before inserting it, build the line
 * through `widgetLine` (the one place that decides bare versus quoted values). Controlled by the designer, which
 * performs the insertion; the server validates the line when it is parsed.
 */
import { useState } from "react";

import type { ReportWidget } from "../api/reportLayouts";
import type { ReportRunValues } from "../api/reports";
import { useStrings } from "../context/TerminologyContext";
import { widgetLine } from "../utils/reportLayoutText";
import { Badge } from "./Badge";
import { TextField } from "./FormFields";
import { ReportParamsForm } from "./ReportParamsForm";

/** @param widgets The parts available to the scope. @param onInsert Called with the line to put on its own line at the caret. */
export function ReportLayoutWidgetPicker({ widgets, onInsert }: { widgets: ReportWidget[]; onInsert: (line: string) => void }) {
  const text = useStrings().reportLayouts;
  const [filter, setFilter] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [values, setValues] = useState<ReportRunValues>({});

  if (widgets.length === 0) return <p className="text-muted">{text.widgetsNone}</p>;

  const needle = filter.trim().toLowerCase();
  const shown = widgets.filter(
    (w) => needle === "" || w.title.toLowerCase().includes(needle) || w.report_title.toLowerCase().includes(needle) || w.module_name.toLowerCase().includes(needle),
  );
  const selected = widgets.find((w) => w.key === selectedKey) ?? null;
  const reports = [...new Set(shown.map((w) => `${w.module_name} · ${w.report_title}`))];

  return (
    <div className="stack">
      <p className="text-muted" style={{ margin: 0 }}>{text.widgetsHint}</p>
      <TextField helpNotNeeded label={text.widgetsFilter} value={filter} onChange={setFilter} />
      {shown.length === 0 && <p className="text-muted" style={{ margin: 0 }}>{text.widgetsNoMatch}</p>}
      {reports.map((report) => (
        <section key={report} className="stack" style={{ gap: "var(--space-1)" }} aria-label={report}>
          <h3 style={{ margin: 0, fontSize: "1rem" }}>{report}</h3>
          <ul className="layout-field-list">
            {shown.filter((w) => `${w.module_name} · ${w.report_title}` === report).map((widget) => (
              <li key={widget.key} className="row" style={{ justifyContent: "space-between" }}>
                <button
                  type="button"
                  className={widget.key === selectedKey ? "btn btn-sm btn-primary" : "btn btn-sm"}
                  aria-pressed={widget.key === selectedKey}
                  title={widget.description || undefined}
                  onClick={() => {
                    setSelectedKey(widget.key);
                    setValues({});
                  }}
                >
                  {widget.title}
                </button>
                <Badge>{text.widgetKind[widget.kind] ?? widget.kind}</Badge>
              </li>
            ))}
          </ul>
        </section>
      ))}
      {selected && (
        <div className="stack card" role="group" aria-label={text.widgetSettings}>
          <strong>{selected.title}</strong>
          {selected.description && <span className="text-muted">{selected.description}</span>}
          <ReportParamsForm
            params={selected.params}
            values={values}
            onChange={(name, value) => setValues((current) => ({ ...current, [name]: value }))}
          />
          <code style={{ overflowWrap: "anywhere" }} aria-label={text.widgetPreview}>{widgetLine(selected, values)}</code>
          <div>
            <button type="button" className="btn btn-primary" onClick={() => onInsert(widgetLine(selected, values))}>
              {text.widgetInsert}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
