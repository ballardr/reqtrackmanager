/**
 * Module: components/ReportGridField
 *
 * The block panel's control for a custom table (`grid` block): a read-only summary ("3 columns · 5 rows · 2 merged") and an
 * Edit table button that opens the table editor in a dialog at full width.
 *
 * Responsibilities:
 * - Keep a draft of the table while the dialog is open, with undo and redo (Ctrl+Z, Ctrl+Y) over the draft, so Cancel discards
 *   every change and Save hands the columns, rows and header count back in one call.
 * - Leave the rest of the block (borders, alignment, colours, the table's own font and size) to the panel's ordinary fields.
 *
 * Design decisions: a table does not fit the side panel, so editing happens in a `Modal` as the custom shape's SVG does;
 * the panel keeps only a summary, because a block shows no editable value on itself (all edits are in the block editor). Undo history
 * lives here, not in the editor, so the editor stays a controlled component.
 */
import { Redo2, Undo2 } from "lucide-react";
import { useState, type KeyboardEvent, type ReactNode } from "react";

import { useStrings } from "../context/TerminologyContext";
import type { ReportFontChoice } from "../api/reportLayouts";
import { gridCounts, shapeOf, type GridRow, type Obj } from "../utils/reportGrid";
import { DEFAULT_COLOUR_CONTEXT, type ColourContext, type ColourEntry } from "../utils/reportColours";
import { FieldCaption } from "./FieldHelp";
import { FormActions } from "./FormActions";
import { Modal } from "./Modal";
import { ReportGridEditor, type GridDraft } from "./ReportGridEditor";

/** Past and future states of a draft; `present` is what the editor shows. */
interface History {
  past: GridDraft[];
  present: GridDraft;
  future: GridDraft[];
}

/** Keys the dialog reads and writes on the block. */
export interface GridPatch {
  columns: Obj[];
  rows: GridRow[];
  header_rows: number | undefined;
}

/**
 * @param label The field's caption.
 * @param help The field's help text.
 * @param node The `grid` block: its `columns`, `rows`, `header_rows` and its own style keys.
 * @param onSave Called with the new columns, rows and header count (`undefined` when none) when the dialog is saved.
 * @param renderCellText Draws the field that edits one cell's text.
 * @param colours The branding colour and organisation scheme, which the colour fields offer.
 * @param palette The layout's own colour scheme.
 * @param fonts The fonts a column may choose.
 * @param disabled Shows the summary only.
 */
export function ReportGridField({
  label, help, node, onSave, renderCellText, colours = DEFAULT_COLOUR_CONTEXT, palette = [], fonts, disabled = false,
}: {
  label: string;
  help?: string;
  node: Obj;
  onSave: (patch: GridPatch) => void;
  renderCellText: (cell: Obj, onText: (text: string) => void, label: string) => ReactNode;
  colours?: ColourContext;
  palette?: ColourEntry[];
  fonts?: ReportFontChoice[];
  disabled?: boolean;
}) {
  const text = useStrings().reportGrid;
  const [history, setHistory] = useState<History | null>(null);
  const counts = gridCounts(node);

  const open = () => setHistory({ past: [], present: shapeOf(node), future: [] });
  const change = (next: GridDraft) => setHistory((h) => (h ? { past: [...h.past, h.present], present: next, future: [] } : h));
  const undo = () => setHistory((h) => (h && h.past.length > 0 ? { past: h.past.slice(0, -1), present: h.past[h.past.length - 1], future: [h.present, ...h.future] } : h));
  const redo = () => setHistory((h) => (h && h.future.length > 0 ? { past: [...h.past, h.present], present: h.future[0], future: h.future.slice(1) } : h));

  /** Ctrl+Z / Ctrl+Y outside a text field; a field keeps its own undo. */
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || !(event.ctrlKey || event.metaKey)) return;
    const key = event.key.toLowerCase();
    if (key === "z" && !event.shiftKey) { event.preventDefault(); undo(); }
    else if (key === "y" || (key === "z" && event.shiftKey)) { event.preventDefault(); redo(); }
  };

  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      <FieldCaption label={label} help={help} />
      <p style={{ margin: 0 }} data-testid="grid-summary">{text.summary(counts.columns, counts.rows, counts.merged)}</p>
      <p className="text-muted" style={{ margin: 0 }}>{text.summaryHint}</p>
      <div>
        <button type="button" className="btn btn-sm" onClick={open}>{disabled ? text.view : text.edit}</button>
      </div>
      {history && (
        <Modal title={text.dialogTitle} size="lg" onClose={() => setHistory(null)}>
          {/* The keys are handled on the dialog's body so Ctrl+Z works once focus is anywhere inside it. */}
          <div className="stack" onKeyDown={onKeyDown}>
            {/* A read-only table has nothing to save; the dialog's own close button ends the view. */}
            {!disabled && (
              <FormActions
                onCancel={() => setHistory(null)}
                onSave={() => {
                  onSave({
                    columns: history.present.columns, rows: history.present.rows,
                    header_rows: history.present.header_rows > 0 ? history.present.header_rows : undefined,
                  });
                  setHistory(null);
                }}
                leading={(
                  <div className="row">
                    <button type="button" className="btn btn-sm btn-icon" aria-label={text.undo} disabled={history.past.length === 0} onClick={undo}>
                      <Undo2 size={14} aria-hidden="true" />
                    </button>
                    <button type="button" className="btn btn-sm btn-icon" aria-label={text.redo} disabled={history.future.length === 0} onClick={redo}>
                      <Redo2 size={14} aria-hidden="true" />
                    </button>
                  </div>
                )}
              />
            )}
            <ReportGridEditor
              value={history.present} onChange={change} gridStyle={node} colours={colours} palette={palette} fonts={fonts}
              renderCellText={renderCellText} readOnly={disabled}
            />
          </div>
        </Modal>
      )}
    </div>
  );
}
