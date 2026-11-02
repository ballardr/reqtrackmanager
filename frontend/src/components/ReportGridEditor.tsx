/**
 * Module: components/ReportGridEditor
 *
 * The editor for a custom table (`grid` block): a drawn grid of cells that are selected with the mouse or the keyboard, a
 * toolbar that merges, aligns and colours the selection, controls that add and remove rows and columns, and fields for the
 * selected cell's text, its row's height and its column's width, font and size.
 *
 * Responsibilities:
 * - Own the selection (anchor and focus positions, widened so a merged cell is never cut) and turn every toolbar action into
 *   one call of `utils/reportGrid`, reporting the result as a whole new `GridDraft`.
 * - Draw the grid as `role="grid"` with a named row and column for each cell, the span of a merged cell, a dashed marker on a
 *   blank cell and the colours the cascade gives each cell.
 * - Warn (never block) about a text and fill pair that is hard to read, and say why a refused action was refused.
 *
 * Design decisions: controlled, with no history of its own (the dialog around it keeps undo). The cell text is edited in a
 * field under the grid, not inside the drawn cell, so a merged cell has one obvious editing target and the block editor keeps
 * its "one editing place" rule. Colours go through the shared `ColourChoiceField`. One tab stop for the whole grid, with the
 * focused cell named by `aria-activedescendant`, as a spreadsheet does.
 */
import {
  AlignCenter, AlignJustify, AlignLeft, AlignRight, AlignVerticalJustifyCenter, AlignVerticalJustifyEnd, AlignVerticalJustifyStart, Bold,
  Merge, Split,
} from "lucide-react";
import { useId, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";

import { useStrings } from "../context/TerminologyContext";
import { contrastRatio } from "../utils/color";
import {
  addColumn, addRow, cellAt, effectiveStyle, hasMerged, mergeCells, originsIn, ownerOf, placedCells, removeColumn, removeRow,
  selectionRect, setCellText, setColumnLook, setColumnWidth, setHeaderRows, setRowHeight, styleCells, styleColumns, styleRows, unmergeCells,
  type GridPos, type GridResult, type GridShape, type GridStylePatch, type Obj,
} from "../utils/reportGrid";
import { DEFAULT_COLOUR_CONTEXT, resolveColourWord, type ColourContext, type ColourEntry } from "../utils/reportColours";
import type { ReportFontChoice } from "../api/reportLayouts";
import { ColourChoiceField } from "./ColourChoiceField";
import { FontChoiceField } from "./FontChoiceField";
import { TextField } from "./FormFields";
import { FieldHelp } from "./FieldHelp";
import { LabeledSelect } from "./LabeledSelect";
import { Tooltip } from "./Tooltip";

/** What the editor changes: the table's columns, rows and header count (its borders and own style stay in the block panel). */
export type GridDraft = GridShape;

/** The text that reads as unreadable below this ratio, as the server judges it. */
const MIN_CONTRAST = 4.5;
const ALIGNMENTS = ["left", "center", "right", "justify"] as const;
const VALIGNMENTS = ["top", "middle", "bottom"] as const;
const ALIGN_ICONS = { left: AlignLeft, center: AlignCenter, right: AlignRight, justify: AlignJustify };
const VALIGN_ICONS = { top: AlignVerticalJustifyStart, middle: AlignVerticalJustifyCenter, bottom: AlignVerticalJustifyEnd };
type Scope = "cells" | "columns" | "rows";

/** A column width as a CSS track: a share becomes a flexible track, a length a fixed one, and anything else shares what is left. */
function trackOf(width: unknown): string {
  if (typeof width === "string") {
    const percent = /^(\d+(?:\.\d+)?)%$/.exec(width);
    if (percent) return `minmax(5rem, ${percent[1]}fr)`;
    const length = /^(\d+(?:\.\d+)?)\s*(cm|mm)$/.exec(width);
    if (length) return `minmax(5rem, ${length[1]}${length[2]})`;
  }
  return "minmax(5rem, 1fr)";
}

function IconToggle({ label, pressed, onClick, disabled, children }: {
  label: string; pressed?: boolean; onClick: () => void; disabled?: boolean; children: ReactNode;
}) {
  return (
    <Tooltip label={label}>
      <button
        type="button" className={`btn btn-sm btn-icon${pressed ? " btn-marked" : ""}`} aria-label={label} aria-pressed={pressed}
        disabled={disabled} onClick={onClick}
      >
        {children}
      </button>
    </Tooltip>
  );
}

/**
 * @param value The table being edited.
 * @param onChange Called with the whole new table after each action.
 * @param gridStyle The table's own style keys (`align`, `fill` ...), the last layer of the cascade.
 * @param colours The branding colour and the organisation's colour scheme, which the colour fields offer.
 * @param palette The layout's own colour scheme.
 * @param fonts The fonts a column may choose; the four standard ones where absent.
 * @param renderCellText Draws the field that edits one cell's text (the block editor's text field with its placeholders).
 * @param readOnly Draws the table without any control that changes it.
 */
export function ReportGridEditor({
  value, onChange, gridStyle = {}, colours = DEFAULT_COLOUR_CONTEXT, palette = [], fonts, renderCellText, readOnly = false,
}: {
  value: GridDraft;
  onChange: (next: GridDraft) => void;
  gridStyle?: Obj;
  colours?: ColourContext;
  palette?: ColourEntry[];
  fonts?: ReportFontChoice[];
  renderCellText: (cell: Obj, onText: (text: string) => void, label: string) => ReactNode;
  readOnly?: boolean;
}) {
  const text = useStrings().reportGrid;
  const idBase = useId();
  const [anchor, setAnchor] = useState<GridPos>({ r: 0, c: 0 });
  const [focus, setFocus] = useState<GridPos>({ r: 0, c: 0 });
  const [scope, setScope] = useState<Scope>("cells");
  const [note, setNote] = useState<{ problem: boolean; message: string } | null>(null);
  const dragging = useRef(false);
  const textHost = useRef<HTMLDivElement>(null);

  const shape: GridShape = value;
  const rowCount = shape.rows.length;
  const columnCount = shape.columns.length;
  const clamp = (pos: GridPos): GridPos => ({ r: Math.max(0, Math.min(pos.r, rowCount - 1)), c: Math.max(0, Math.min(pos.c, columnCount - 1)) });
  const a = clamp(anchor);
  const f = clamp(focus);
  const rect = selectionRect(shape, a, f);
  const active = ownerOf(shape, a);
  const activeCell = cellAt(shape, active) ?? {};
  const placed = useMemo(() => placedCells(shape), [shape]);
  const origins = originsIn(shape, rect);
  const selected = new Set(origins.map((p) => `${p.r}:${p.c}`));
  const styleOf = (pos: GridPos) => effectiveStyle(gridStyle, shape, pos);
  const activeStyle = styleOf(active);

  const commit = (next: GridShape, done?: string) => {
    onChange(next);
    setNote(done ? { problem: false, message: done } : null);
  };
  const run = (result: GridResult, done: string, after?: (next: GridShape) => void) => {
    if ("problem" in result) {
      setNote({ problem: true, message: text.problems[result.problem] ?? result.problem });
      return;
    }
    commit(result.shape, done);
    after?.(result.shape);
  };

  const apply = (patch: GridStylePatch) => {
    if (readOnly) return;
    if (scope === "columns") commit(styleColumns(shape, rect.c0, rect.c1, patch));
    else if (scope === "rows") commit(styleRows(shape, rect.r0, rect.r1, patch));
    else commit(styleCells(shape, rect, patch));
  };

  const allEffective = <T,>(pick: (s: ReturnType<typeof styleOf>) => T, expected: T) => origins.length > 0 && origins.every((p) => pick(styleOf(p)) === expected);
  // Merge stays on for a range over the header so a click can say why it is refused; only a single cell has nothing to merge.
  const mergePossible = origins.length >= 2;
  const unmergePossible = hasMerged(shape, rect);

  const lowContrast = origins.some((p) => {
    const style = styleOf(p);
    const fill = style.fill ? resolveColourWord(style.fill, colours, palette) : null;
    // As the run's warning reads it: a text colour left unset is black on a fill.
    const colour = style.color ? resolveColourWord(style.color, colours, palette) : "#000000";
    return fill !== null && colour !== null && contrastRatio(fill, colour) < MIN_CONTRAST;
  });

  const move = (key: string, extend: boolean) => {
    const from = ownerOf(shape, f);
    const cell = cellAt(shape, from) ?? {};
    const colspan = typeof cell.colspan === "number" ? cell.colspan : 1;
    const rowspan = typeof cell.rowspan === "number" ? cell.rowspan : 1;
    const target =
      key === "ArrowRight" ? { r: from.r, c: from.c + colspan }
        : key === "ArrowLeft" ? { r: from.r, c: from.c - 1 }
          : key === "ArrowDown" ? { r: from.r + rowspan, c: from.c }
            : { r: from.r - 1, c: from.c };
    const next = clamp(target);
    setFocus(next);
    if (!extend) setAnchor(next);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key.startsWith("Arrow")) {
      event.preventDefault();
      move(event.key, event.shiftKey);
    } else if (event.key === "Enter" || event.key === "F2") {
      event.preventDefault();
      textHost.current?.querySelector<HTMLElement>("textarea, input")?.focus();
    }
  };

  const cellId = (pos: GridPos) => `${idBase}-r${pos.r}c${pos.c}`;
  const row = rect.r0;
  const column = rect.c0;
  const rowObj = (shape.rows[row] ?? {}) as Obj;
  const heightValue = typeof rowObj.height === "number" ? rowObj.height : undefined;
  const heightUnit = rowObj.height_unit === "mm" ? "mm" : "cm";
  const columnFont = typeof shape.columns[column]?.font === "string" ? (shape.columns[column].font as string) : "";
  const columnSize = typeof shape.columns[column]?.size === "number" ? (shape.columns[column].size as number) : undefined;
  const widthValue = typeof shape.columns[column]?.width === "string" ? (shape.columns[column].width as string) : "";

  const gridTemplate = shape.columns.map((c) => trackOf(c.width)).join(" ");
  const lastHeader = shape.header_rows;

  return (
    <div className="stack grid-editor">
      {!readOnly && (
        <>
          <div className="row grid-editor__toolbar" role="toolbar" aria-label={text.formatting}>
            <IconToggle label={text.merge} disabled={!mergePossible} onClick={() => run(mergeCells(shape, rect), text.changed.merged, () => setAnchor({ r: rect.r0, c: rect.c0 }))}>
              <Merge size={14} aria-hidden="true" />
            </IconToggle>
            <IconToggle label={text.unmerge} disabled={!unmergePossible} onClick={() => commit(unmergeCells(shape, rect), text.changed.unmerged)}>
              <Split size={14} aria-hidden="true" />
            </IconToggle>
            <span className="grid-editor__divider" aria-hidden="true" />
            {ALIGNMENTS.map((word) => {
              const Icon = ALIGN_ICONS[word];
              return (
                <IconToggle key={word} label={text.alignLabels[word]} pressed={allEffective((s) => s.align, word)} onClick={() => apply({ align: word })}>
                  <Icon size={14} aria-hidden="true" />
                </IconToggle>
              );
            })}
            <span className="grid-editor__divider" aria-hidden="true" />
            {VALIGNMENTS.map((word) => {
              const Icon = VALIGN_ICONS[word];
              return (
                <IconToggle key={word} label={text.valignLabels[word]} pressed={allEffective((s) => s.valign, word)} onClick={() => apply({ valign: word })}>
                  <Icon size={14} aria-hidden="true" />
                </IconToggle>
              );
            })}
            <span className="grid-editor__divider" aria-hidden="true" />
            <IconToggle label={text.bold} pressed={allEffective((s) => s.bold, true)} onClick={() => apply({ bold: !allEffective((s) => s.bold, true) })}>
              <Bold size={14} aria-hidden="true" />
            </IconToggle>
            <ColourChoiceField
              helpNotNeeded label={text.fill} value={activeStyle.fill ?? ""} context={colours} layoutPalette={palette} emptyLabel={text.inherit}
              onChange={(word) => apply({ fill: word === "" ? undefined : word })}
            />
            <ColourChoiceField
              helpNotNeeded label={text.textColour} value={activeStyle.color ?? ""} context={colours} layoutPalette={palette} emptyLabel={text.inherit}
              onChange={(word) => apply({ color: word === "" ? undefined : word })}
            />
            <LabeledSelect
              helpNotNeeded label={text.applyTo} value={scope} placeholder={null} onChange={(next) => setScope(next as Scope)}
              options={(["cells", "columns", "rows"] as const).map((key) => ({ value: key, label: text.scopes[key] }))}
            />
          </div>
          <div className="row grid-editor__toolbar" role="toolbar" aria-label={text.structure}>
            <button type="button" className="btn btn-sm" onClick={() => run(addRow(shape, rect.r0), text.changed.rowAdded)}>{text.addRowAbove}</button>
            <button type="button" className="btn btn-sm" onClick={() => run(addRow(shape, rect.r1 + 1), text.changed.rowAdded, () => setAnchor({ r: rect.r1 + 1, c: column }))}>{text.addRowBelow}</button>
            <button
              type="button" className="btn btn-sm" disabled={rowCount <= 1}
              onClick={() => run(removeRow(shape, rect.r0), text.changed.rowRemoved)}
            >
              {text.removeRow}
            </button>
            <span className="grid-editor__divider" aria-hidden="true" />
            <button type="button" className="btn btn-sm" onClick={() => run(addColumn(shape, rect.c0), text.changed.columnAdded)}>{text.addColumnLeft}</button>
            <button type="button" className="btn btn-sm" onClick={() => run(addColumn(shape, rect.c1 + 1), text.changed.columnAdded, () => setAnchor({ r: row, c: rect.c1 + 1 }))}>{text.addColumnRight}</button>
            <button
              type="button" className="btn btn-sm" disabled={columnCount <= 1}
              onClick={() => run(removeColumn(shape, rect.c0), text.changed.columnRemoved)}
            >
              {text.removeColumn}
            </button>
            <FieldHelp label={text.selectionHelpLabel} help={text.selectionHint} />
          </div>
        </>
      )}
      <div className="grid-editor__scroller">
        <div
          role="grid" aria-label={text.gridLabel} aria-rowcount={rowCount} aria-colcount={columnCount} aria-multiselectable="true"
          aria-activedescendant={cellId(ownerOf(shape, f))} tabIndex={0} className="grid-editor__grid" onKeyDown={onKeyDown}
          style={{ gridTemplateColumns: gridTemplate }} onMouseUp={() => { dragging.current = false; }}
        >
          {placed.map(({ r, c, cell, rowspan, colspan }) => {
            const style = styleOf({ r, c });
            const fill = style.fill ? resolveColourWord(style.fill, colours, palette) : null;
            const colour = style.color ? resolveColourWord(style.color, colours, palette) : null;
            const body = typeof cell.text === "string" ? cell.text : "";
            const header = r < lastHeader;
            const css: CSSProperties = {
              gridRow: `${r + 1} / span ${rowspan}`, gridColumn: `${c + 1} / span ${colspan}`,
              textAlign: style.align === "justify" ? "justify" : (style.align as CSSProperties["textAlign"]),
              alignItems: style.valign === "middle" ? "center" : style.valign === "bottom" ? "flex-end" : "flex-start",
              fontWeight: style.bold ? 700 : undefined,
              background: fill ?? undefined, color: colour ?? undefined,
            };
            const first = body.split("\n")[0];
            return (
              <div
                key={`${r}:${c}`} id={cellId({ r, c })} role={header ? "columnheader" : "gridcell"}
                aria-label={`${text.cellName(r + 1, c + 1)}${first ? `: ${first}` : ""}`}
                aria-rowindex={r + 1} aria-colindex={c + 1} aria-rowspan={rowspan > 1 ? rowspan : undefined} aria-colspan={colspan > 1 ? colspan : undefined}
                aria-selected={selected.has(`${r}:${c}`)}
                className={[
                  "grid-editor__cell", selected.has(`${r}:${c}`) ? "grid-editor__cell--selected" : "",
                  active.r === r && active.c === c ? "grid-editor__cell--active" : "", header ? "grid-editor__cell--header" : "",
                  r + rowspan === lastHeader ? "grid-editor__cell--header-edge" : "",
                ].filter(Boolean).join(" ")}
                style={css}
                onMouseDown={(event) => {
                  if (event.button !== 0) return;
                  dragging.current = true;
                  if (event.shiftKey) setFocus({ r, c });
                  else { setAnchor({ r, c }); setFocus({ r, c }); }
                }}
                onMouseEnter={(event) => { if (dragging.current && event.buttons === 1) setFocus({ r, c }); }}
              >
                {body === "" ? <span className="grid-editor__blank">{text.blankCell}</span> : <span className="grid-editor__text">{body}</span>}
                {(rowspan > 1 || colspan > 1) && <span className="grid-editor__span" aria-hidden="true">{text.cellSpan(rowspan, colspan)}</span>}
              </div>
            );
          })}
        </div>
      </div>
      {note && <p role={note.problem ? "alert" : "status"} className={note.problem ? "field-error" : "text-muted"} style={{ margin: 0 }}>{note.message}</p>}
      {lowContrast && <p role="alert" className="field-error" style={{ margin: 0 }}>{text.lowContrast}</p>}
      <div ref={textHost}>
        {renderCellText(activeCell, (next) => commit(setCellText(shape, active, next)), text.cellText(active.r + 1, active.c + 1))}
      </div>
      {!readOnly && (
        <div className="row grid-editor__sizes">
          <TextField
            help={text.rowHeightHelp} label={text.rowHeight(row + 1)} value={heightValue === undefined ? "" : String(heightValue)}
            inputProps={{ type: "number", step: "any", min: 0 }}
            onChange={(t) => {
              if (t.trim() === "") commit(setRowHeight(shape, row, undefined, heightUnit));
              else if (Number.isFinite(Number(t))) commit(setRowHeight(shape, row, Number(t), heightUnit));
            }}
          />
          <LabeledSelect
            helpNotNeeded label={text.heightUnit} value={heightUnit} placeholder={null} disabled={heightValue === undefined}
            options={[{ value: "cm", label: "cm" }, { value: "mm", label: "mm" }]}
            onChange={(unit) => commit(setRowHeight(shape, row, heightValue, unit === "mm" ? "mm" : "cm"))}
          />
          <TextField
            help={text.columnWidthHelp} label={text.columnWidth(column + 1)} value={widthValue} placeholder={text.columnWidthPlaceholder}
            onChange={(t) => commit(setColumnWidth(shape, column, t))}
          />
          <FontChoiceField
            help={text.columnFontHelp} label={text.columnFont(column + 1)} value={columnFont} fonts={fonts} emptyLabel={text.columnFontEmpty}
            onChange={(key) => commit(setColumnLook(shape, column, "font", key))}
          />
          <TextField
            help={text.columnSizeHelp} label={text.columnSize(column + 1)} value={columnSize === undefined ? "" : String(columnSize)}
            placeholder={text.columnSizePlaceholder} inputProps={{ type: "number", step: 0.5, min: 6, max: 72 }}
            onChange={(t) => {
              if (t.trim() === "") commit(setColumnLook(shape, column, "size", undefined));
              else if (Number.isFinite(Number(t))) commit(setColumnLook(shape, column, "size", Number(t)));
            }}
          />
          <TextField
            help={text.headerRowsHelp} label={text.headerRows}
            value={String(shape.header_rows)} inputProps={{ type: "number", min: 0, max: rowCount }}
            onChange={(t) => {
              const count = Number(t);
              if (t.trim() !== "" && Number.isInteger(count)) run(setHeaderRows(shape, count), "");
            }}
          />
        </div>
      )}
    </div>
  );
}
