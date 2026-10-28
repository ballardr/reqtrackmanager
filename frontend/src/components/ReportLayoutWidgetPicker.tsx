/**
 * Module: components/ReportLayoutWidgetPicker
 *
 * The designer's widget picker: lists the report parts a `[[widget.key ...]]` line can embed as a tree (module, then
 * report, then the report's components), every branch collapsed until the author opens it or searches. It lets the
 * author set the report's parameters with the same form the Reports page uses (`ReportParamsForm`) and inserts the
 * finished line.
 *
 * Responsibilities: filter by title, report or module (a search opens every branch that still holds a match), show
 * what the line will read before inserting it, build the line through `widgetLine` (the one place that decides bare
 * versus quoted values). Controlled by the designer, which performs the insertion; the server validates the line when
 * it is parsed.
 */
import { useMemo, useState } from "react";

import type { ReportWidget } from "../api/reportLayouts";
import type { ReportRunValues } from "../api/reports";
import { useStrings } from "../context/TerminologyContext";
import { widgetLine } from "../utils/reportLayoutText";
import { Badge } from "./Badge";
import { TextField } from "./FormFields";
import { ReportParamsForm } from "./ReportParamsForm";
import { TreeView, type TreeViewNode } from "./TreeView";

/** A branch (module or report) or a leaf (one component a line can embed). */
interface WidgetNode extends TreeViewNode<WidgetNode> {
  kind: "module" | "report" | "widget";
  name: string;
  widget?: ReportWidget;
}

/** Groups `widgets` by module and then by report, keeping the server's order within each. */
function buildWidgetTree(widgets: ReportWidget[]): WidgetNode[] {
  const modules = new Map<string, WidgetNode>();
  const reports = new Map<string, WidgetNode>();
  for (const widget of widgets) {
    let moduleNode = modules.get(widget.module_name);
    if (!moduleNode) {
      moduleNode = { id: `m:${widget.module_name}`, kind: "module", name: widget.module_name, children: [] };
      modules.set(widget.module_name, moduleNode);
    }
    const reportKey = `${widget.module_name}\u0000${widget.report_title}`;
    let reportNode = reports.get(reportKey);
    if (!reportNode) {
      reportNode = { id: `r:${reportKey}`, kind: "report", name: widget.report_title, children: [] };
      reports.set(reportKey, reportNode);
      moduleNode.children.push(reportNode);
    }
    reportNode.children.push({ id: `w:${widget.key}`, kind: "widget", name: widget.title, widget, children: [] });
  }
  return [...modules.values()];
}

/** The ids of every branch of `nodes`. */
function branchIds(nodes: WidgetNode[]): string[] {
  return nodes.flatMap((node) => (node.children.length > 0 ? [node.id, ...branchIds(node.children)] : []));
}

/** @param widgets The parts available to the scope. @param onInsert Called with the line to put on its own line at the caret. */
export function ReportLayoutWidgetPicker({ widgets, onInsert }: { widgets: ReportWidget[]; onInsert: (line: string) => void }) {
  const text = useStrings().reportLayouts;
  const [filter, setFilter] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [values, setValues] = useState<ReportRunValues>({});
  const [openIds, setOpenIds] = useState<ReadonlySet<string>>(new Set());

  const needle = filter.trim().toLowerCase();
  const shown = useMemo(
    () => widgets.filter(
      (w) => needle === "" || w.title.toLowerCase().includes(needle) || w.report_title.toLowerCase().includes(needle) || w.module_name.toLowerCase().includes(needle),
    ),
    [widgets, needle],
  );
  const tree = useMemo(() => buildWidgetTree(shown), [shown]);
  const expanded = useMemo(() => (needle === "" ? openIds : new Set(branchIds(tree))), [needle, openIds, tree]);

  if (widgets.length === 0) return <p className="text-muted">{text.widgetsNone}</p>;

  const selected = widgets.find((w) => w.key === selectedKey) ?? null;

  return (
    <div className="stack">
      <p className="text-muted" style={{ margin: 0 }}>{text.widgetsHint}</p>
      <TextField helpNotNeeded label={text.widgetsFilter} value={filter} onChange={setFilter} />
      {shown.length === 0 && <p className="text-muted" style={{ margin: 0 }}>{text.widgetsNoMatch}</p>}
      <TreeView
        nodes={tree}
        nodeLabel={(node) => node.name}
        expanded={expanded}
        onToggle={(id, open) => {
          if (needle !== "") return;
          setOpenIds((current) => {
            const next = new Set(current);
            if (open) next.add(id);
            else next.delete(id);
            return next;
          });
        }}
        renderNode={(node) => {
          const widget = node.widget;
          if (node.kind !== "widget" || !widget) {
            return node.kind === "module" ? <strong>{node.name}</strong> : <span>{node.name}</span>;
          }
          return (
            <span className="row" style={{ justifyContent: "space-between", flex: 1 }}>
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
            </span>
          );
        }}
      />
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
