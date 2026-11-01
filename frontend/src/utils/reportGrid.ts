/**
 * Module: utils/reportGrid
 *
 * The pure model behind the custom table editor: a `grid` block's columns and rows as an editable matrix, and the
 * operations the editor offers on it (merge, unmerge, style a selection, add and remove rows and columns).
 *
 * Responsibilities:
 * - Place a grid's cells on a rows x columns matrix the way the server does (`services/report_grid.place_spans`): a merged
 *   region is stored once on its top-left cell and the covered positions are omitted from the row.
 * - Return a new `{ columns, rows, header_rows }` for every operation, never changing the input; a refused operation
 *   returns a problem key instead of a half-applied result.
 * - Resolve a cell's style through the cascade (cell, row, column, grid) so the editor draws what a run prints.
 *
 * Design decisions: every operation works on a dense matrix (`Slot[][]`) and writes it back, so a merge that spans the
 * insertion or removal point is adjusted in one place. Column operations are the row operations on the transposed
 * matrix (`colspan` and `rowspan` swapped), which keeps one implementation of the hard case. The server stays the judge:
 * the editor refuses what it can see is wrong (a merge across the header, a limit) and the saved tree is still checked.
 * A tree that is short or overflows is normalised on the first edit (short rows get blank cells).
 */

export type Obj = Record<string, unknown>;

/** One row of a custom table as the tree stores it: its own style and height, and the cells that start in it. */
export interface GridRow {
  cells: Obj[];
  [key: string]: unknown;
}

/** The most columns and rows a custom table may have (the server's limits). */
export const MAX_GRID_COLUMNS = 20;
export const MAX_GRID_ROWS = 200;

/** The cascading style keys of a grid, column, row and cell. */
export const GRID_STYLE_KEYS = ["align", "valign", "fill", "color", "bold"] as const;
export type GridStyleKey = (typeof GRID_STYLE_KEYS)[number];

/** The parts of a `grid` block the table editor changes. */
export interface GridShape {
  columns: Obj[];
  rows: GridRow[];
  header_rows: number;
}

/** A rectangle of grid positions, inclusive at both ends. */
export interface GridRect {
  r0: number;
  c0: number;
  r1: number;
  c1: number;
}

/** A position in the grid. */
export interface GridPos {
  r: number;
  c: number;
}

/** One position: the cell that starts here (`cell`), or `null` when a merge from another position covers it. */
interface Slot {
  cell: Obj | null;
  /** The position of the cell that owns this one (itself for a cell that starts here). */
  owner: GridPos;
}

/** A matrix with the row properties (`height`, style) and the column properties kept beside it. */
interface Dense {
  columns: Obj[];
  meta: Obj[];
  slots: Slot[][];
  header: number;
}

/** What went wrong with a refused operation; the editor turns it into a message. */
export type GridProblem = "acrossHeader" | "tooManyRows" | "tooManyColumns" | "lastRow" | "lastColumn" | "nothingToMerge";

export type GridResult = { shape: GridShape } | { problem: GridProblem };

const num = (value: unknown, fallback = 1): number => (typeof value === "number" && Number.isInteger(value) && value >= 1 ? value : fallback);
const spanOf = (cell: Obj) => ({ cols: num(cell.colspan), rows: num(cell.rowspan) });

function withSpan(cell: Obj, cols: number, rows: number): Obj {
  const next: Obj = { ...cell };
  if (cols > 1) next.colspan = cols;
  else delete next.colspan;
  if (rows > 1) next.rowspan = rows;
  else delete next.rowspan;
  return next;
}

const blankCell = (): Obj => ({ text: "" });

/** Places the cells of `shape` on a matrix; a short row gets blank cells and a cell that overflows the grid is clipped. */
function toDense(shape: GridShape): Dense {
  const width = shape.columns.length;
  const grid: (Slot | null)[][] = shape.rows.map(() => Array.from({ length: width }, (): Slot | null => null));
  const meta: Obj[] = [];
  shape.rows.forEach((row, r) => {
    const { cells, ...rest } = row;
    meta.push(rest);
    let c = 0;
    for (const raw of Array.isArray(cells) ? cells : []) {
      while (c < width && grid[r][c] !== null) c += 1;
      if (c >= width) break;
      const cell = { ...raw };
      const { cols, rows } = spanOf(cell);
      const colSpan = Math.min(cols, width - c);
      const rowSpan = Math.min(rows, shape.rows.length - r);
      for (let dr = 0; dr < rowSpan; dr += 1) {
        for (let dc = 0; dc < colSpan; dc += 1) {
          if (grid[r + dr][c + dc] !== null) continue;
          grid[r + dr][c + dc] = { cell: dr === 0 && dc === 0 ? withSpan(cell, colSpan, rowSpan) : null, owner: { r, c } };
        }
      }
      c += colSpan;
    }
  });
  const slots: Slot[][] = grid.map((row, r) => row.map((slot, c) => slot ?? { cell: blankCell(), owner: { r, c } }));
  return { columns: shape.columns.map((column) => ({ ...column })), meta, slots, header: shape.header_rows };
}

/** Writes a matrix back as rows of cells, leaving out the covered positions. */
function fromDense(dense: Dense): GridShape {
  const rows: GridRow[] = dense.slots.map((row, r) => ({
    ...dense.meta[r],
    cells: row.filter((slot, c) => slot.cell !== null && slot.owner.r === r && slot.owner.c === c).map((slot) => slot.cell as Obj),
  }));
  return { columns: dense.columns, rows, header_rows: dense.header };
}

/** @returns The grid's matrix size. */
export function gridSize(shape: GridShape): { rows: number; columns: number } {
  return { rows: shape.rows.length, columns: shape.columns.length };
}

/** A grid as the block's `columns`, `rows` and `header_rows` keys; absent keys read as one blank cell. */
export function shapeOf(node: Obj): GridShape {
  const columns = Array.isArray(node.columns) ? (node.columns as Obj[]) : [];
  const rows = Array.isArray(node.rows) ? (node.rows as GridRow[]) : [];
  const header = typeof node.header_rows === "number" && Number.isInteger(node.header_rows) ? Math.max(0, Math.min(node.header_rows, rows.length)) : 0;
  return { columns, rows, header_rows: header };
}

/** A new grid of `rows` x `columns` blank cells. */
export function blankShape(rows: number, columns: number): GridShape {
  return {
    columns: Array.from({ length: columns }, () => ({})),
    rows: Array.from({ length: rows }, () => ({ cells: Array.from({ length: columns }, blankCell) })),
    header_rows: 0,
  };
}

/** One cell as drawn: where it starts, how far it spans and the cell itself. */
export interface PlacedGridCell extends GridPos {
  cell: Obj;
  rowspan: number;
  colspan: number;
}

/** @returns Every cell in reading order with its position and span, for drawing. */
export function placedCells(shape: GridShape): PlacedGridCell[] {
  const dense = toDense(shape);
  const out: PlacedGridCell[] = [];
  dense.slots.forEach((row, r) => row.forEach((slot, c) => {
    if (slot.cell !== null && slot.owner.r === r && slot.owner.c === c) {
      const { cols, rows } = spanOf(slot.cell);
      out.push({ r, c, cell: slot.cell, rowspan: rows, colspan: cols });
    }
  }));
  return out;
}

/** The position of the cell that covers `pos` (the position itself when it starts a cell or is outside the grid). */
export function ownerOf(shape: GridShape, pos: GridPos): GridPos {
  const dense = toDense(shape);
  return dense.slots[pos.r]?.[pos.c]?.owner ?? pos;
}

/** The smallest rectangle containing `a` and `b` that cuts no merged cell in half. */
export function selectionRect(shape: GridShape, a: GridPos, b: GridPos): GridRect {
  const dense = toDense(shape);
  const rows = dense.slots.length;
  const cols = dense.columns.length;
  const clamp = (value: number, max: number) => Math.max(0, Math.min(value, max - 1));
  let rect: GridRect = {
    r0: clamp(Math.min(a.r, b.r), rows), c0: clamp(Math.min(a.c, b.c), cols), r1: clamp(Math.max(a.r, b.r), rows), c1: clamp(Math.max(a.c, b.c), cols),
  };
  for (let changed = true; changed;) {
    changed = false;
    for (let r = rect.r0; r <= rect.r1; r += 1) {
      for (let c = rect.c0; c <= rect.c1; c += 1) {
        const owner = dense.slots[r][c].owner;
        const { cols: cs, rows: rs } = spanOf(dense.slots[owner.r][owner.c].cell ?? {});
        const next: GridRect = {
          r0: Math.min(rect.r0, owner.r), c0: Math.min(rect.c0, owner.c),
          r1: Math.max(rect.r1, owner.r + rs - 1), c1: Math.max(rect.c1, owner.c + cs - 1),
        };
        if (next.r0 !== rect.r0 || next.c0 !== rect.c0 || next.r1 !== rect.r1 || next.c1 !== rect.c1) {
          rect = next;
          changed = true;
        }
      }
    }
  }
  return rect;
}

/** The origin positions of the cells inside `rect` (each merged cell once). */
export function originsIn(shape: GridShape, rect: GridRect): GridPos[] {
  const dense = toDense(shape);
  const seen = new Set<string>();
  const out: GridPos[] = [];
  for (let r = rect.r0; r <= rect.r1; r += 1) {
    for (let c = rect.c0; c <= rect.c1; c += 1) {
      const owner = dense.slots[r]?.[c]?.owner;
      if (owner && !seen.has(`${owner.r}:${owner.c}`)) {
        seen.add(`${owner.r}:${owner.c}`);
        out.push(owner);
      }
    }
  }
  return out;
}

/** @returns The cell that starts at `pos`, or `null` when `pos` is outside the grid. */
export function cellAt(shape: GridShape, pos: GridPos): Obj | null {
  const dense = toDense(shape);
  const owner = dense.slots[pos.r]?.[pos.c]?.owner;
  return owner ? dense.slots[owner.r][owner.c].cell : null;
}

/** Whether `rect` holds more than one cell, so Merge applies. */
export function canMerge(shape: GridShape, rect: GridRect): GridResult | { problem: GridProblem } {
  if (originsIn(shape, rect).length < 2) return { problem: "nothingToMerge" };
  if (rect.r0 < shape.header_rows && rect.r1 >= shape.header_rows) return { problem: "acrossHeader" };
  return { shape };
}

/** Whether any cell inside `rect` is merged, so Unmerge applies. */
export function hasMerged(shape: GridShape, rect: GridRect): boolean {
  return originsIn(shape, rect).some((pos) => {
    const { cols, rows } = spanOf(cellAt(shape, pos) ?? {});
    return cols > 1 || rows > 1;
  });
}

/** Merges the cells of `rect` into the one at its top left; the others' text is added after its text, line by line. */
export function mergeCells(shape: GridShape, rect: GridRect): GridResult {
  const check = canMerge(shape, rect);
  if ("problem" in check) return check;
  const dense = toDense(shape);
  const owners = originsIn(shape, rect);
  const texts = owners.map((p) => String(dense.slots[p.r][p.c].cell?.text ?? "")).filter((t) => t !== "");
  const top = dense.slots[rect.r0][rect.c0].cell ?? {};
  for (let r = rect.r0; r <= rect.r1; r += 1) {
    for (let c = rect.c0; c <= rect.c1; c += 1) dense.slots[r][c] = { cell: null, owner: { r: rect.r0, c: rect.c0 } };
  }
  dense.slots[rect.r0][rect.c0] = {
    cell: { ...withSpan(top, rect.c1 - rect.c0 + 1, rect.r1 - rect.r0 + 1), text: texts.join("\n") }, owner: { r: rect.r0, c: rect.c0 },
  };
  return { shape: fromDense(dense) };
}

/** Splits every merged cell inside `rect` back into single cells; the new cells copy the merged cell's style and start blank. */
export function unmergeCells(shape: GridShape, rect: GridRect): GridShape {
  const dense = toDense(shape);
  for (const pos of originsIn(shape, rect)) {
    const cell = dense.slots[pos.r][pos.c].cell as Obj;
    const { cols, rows } = spanOf(cell);
    if (cols === 1 && rows === 1) continue;
    const style: Obj = Object.fromEntries(GRID_STYLE_KEYS.filter((k) => k in cell).map((k) => [k, cell[k]]));
    for (let r = pos.r; r < pos.r + rows; r += 1) {
      for (let c = pos.c; c < pos.c + cols; c += 1) {
        dense.slots[r][c] = { cell: r === pos.r && c === pos.c ? withSpan(cell, 1, 1) : { text: "", ...style }, owner: { r, c } };
      }
    }
  }
  return fromDense(dense);
}

/** A style change: a key set to a value, or `undefined` to fall back to what the row, column or grid says. */
export type GridStylePatch = Partial<Record<GridStyleKey, string | boolean | undefined>>;

function applyPatch(target: Obj, patch: GridStylePatch): Obj {
  const next: Obj = { ...target };
  for (const [key, value] of Object.entries(patch)) {
    if (value === undefined) delete next[key];
    else next[key] = value;
  }
  return next;
}

function dropKeys(target: Obj, patch: GridStylePatch): Obj {
  const next: Obj = { ...target };
  for (const key of Object.keys(patch)) delete next[key];
  return next;
}

/** Styles the cells inside `rect`. */
export function styleCells(shape: GridShape, rect: GridRect, patch: GridStylePatch): GridShape {
  const dense = toDense(shape);
  for (const pos of originsIn(shape, rect)) dense.slots[pos.r][pos.c].cell = applyPatch(dense.slots[pos.r][pos.c].cell as Obj, patch);
  return fromDense(dense);
}

/**
 * Styles whole columns: the column carries the setting and the single-column cells in it lose their own value for that key, so
 * the setting shows (a cell's own value would otherwise win over the column's).
 */
export function styleColumns(shape: GridShape, from: number, to: number, patch: GridStylePatch): GridShape {
  const dense = toDense(shape);
  for (let c = from; c <= to; c += 1) {
    dense.columns[c] = applyPatch(dense.columns[c], patch);
    dense.slots.forEach((row, r) => {
      const slot = row[c];
      if (slot.cell !== null && slot.owner.r === r && slot.owner.c === c && spanOf(slot.cell).cols === 1) slot.cell = dropKeys(slot.cell, patch);
    });
  }
  return fromDense(dense);
}

/** Styles whole rows, as `styleColumns` does for columns. */
export function styleRows(shape: GridShape, from: number, to: number, patch: GridStylePatch): GridShape {
  const dense = toDense(shape);
  for (let r = from; r <= to; r += 1) {
    dense.meta[r] = applyPatch(dense.meta[r], patch);
    dense.slots[r].forEach((slot, c) => {
      if (slot.cell !== null && slot.owner.r === r && slot.owner.c === c && spanOf(slot.cell).rows === 1) slot.cell = dropKeys(slot.cell, patch);
    });
  }
  return fromDense(dense);
}

/** Sets the text of the cell that covers `pos`. */
export function setCellText(shape: GridShape, pos: GridPos, text: string): GridShape {
  const dense = toDense(shape);
  const owner = dense.slots[pos.r]?.[pos.c]?.owner;
  if (!owner) return shape;
  dense.slots[owner.r][owner.c].cell = { ...(dense.slots[owner.r][owner.c].cell as Obj), text };
  return fromDense(dense);
}

/** Sets or clears (`undefined`) a column's width. */
export function setColumnWidth(shape: GridShape, column: number, width: string | undefined): GridShape {
  const columns = shape.columns.map((c, i) => {
    if (i !== column) return c;
    const next: Obj = { ...c };
    if (width === undefined || width.trim() === "") delete next.width;
    else next.width = width.trim();
    return next;
  });
  return { ...shape, columns };
}

/** Sets or clears (`undefined`) a row's minimum height; clearing also clears the unit. */
export function setRowHeight(shape: GridShape, row: number, height: number | undefined, unit: "cm" | "mm"): GridShape {
  const rows = shape.rows.map((r, i) => {
    if (i !== row) return r;
    const next: GridRow = { ...r };
    if (height === undefined) {
      delete next.height;
      delete next.height_unit;
    } else {
      next.height = height;
      if (unit === "cm") delete next.height_unit;
      else next.height_unit = unit;
    }
    return next;
  });
  return { ...shape, rows };
}

/** Whether the header can be `count` rows: a merge may not cross from the header into the body. */
export function headerRowsProblem(shape: GridShape, count: number): GridProblem | null {
  const dense = toDense(shape);
  if (count <= 0 || count >= dense.slots.length) return null;
  for (let c = 0; c < dense.columns.length; c += 1) {
    const owner = dense.slots[count][c].owner;
    if (owner.r < count) return "acrossHeader";
  }
  return null;
}

/** Sets how many leading rows are the header (clamped to the grid), or refuses when a merge would cross the boundary. */
export function setHeaderRows(shape: GridShape, count: number): GridResult {
  const clamped = Math.max(0, Math.min(count, shape.rows.length));
  const problem = headerRowsProblem(shape, clamped);
  return problem ? { problem } : { shape: { ...shape, header_rows: clamped } };
}

// ---- Adding and removing rows and columns --------------------------------------------------------------------------

/** Swaps rows and columns of a matrix, with each cell's `colspan` and `rowspan` swapped, so a column operation is a row operation. */
function transpose(slots: Slot[][]): Slot[][] {
  const rows = slots.length;
  const cols = rows === 0 ? 0 : slots[0].length;
  const swapSpan = (cell: Obj | null): Obj | null => {
    if (cell === null) return null;
    const { cols: cs, rows: rs } = spanOf(cell);
    return withSpan(cell, rs, cs);
  };
  return Array.from({ length: cols }, (_, c) => Array.from({ length: rows }, (__, r) => {
    const slot = slots[r][c];
    return { cell: swapSpan(slot.cell), owner: { r: slot.owner.c, c: slot.owner.r } };
  }));
}

/** Inserts a blank row so it becomes row `at`; a merge that spans the gap grows by one row. */
function insertRowSlots(slots: Slot[][], at: number): Slot[][] {
  const width = slots[0].length;
  const grown = new Set<string>();
  const below = slots.slice(at);
  const above = slots.slice(0, at);
  const inserted: Slot[] = Array.from({ length: width }, (_, c): Slot => {
    const crossing = at > 0 && at < slots.length && slots[at][c].owner.r < at;
    if (!crossing) return { cell: blankCell(), owner: { r: at, c } };
    const owner = slots[at][c].owner;
    grown.add(`${owner.r}:${owner.c}`);
    return { cell: null, owner };
  });
  const shifted = below.map((row) => row.map((slot): Slot => ({ ...slot, owner: slot.owner.r >= at ? { r: slot.owner.r + 1, c: slot.owner.c } : slot.owner })));
  const next = [...above.map((row) => row.map((slot) => ({ ...slot }))), inserted, ...shifted];
  for (const key of grown) {
    const [r, c] = key.split(":").map(Number);
    const cell = next[r][c].cell as Obj;
    const { cols, rows } = spanOf(cell);
    next[r][c] = { ...next[r][c], cell: withSpan(cell, cols, rows + 1) };
  }
  return next;
}

/** Removes row `r`; a merge that started in it continues from the row below, one row shorter. */
function removeRowSlots(slots: Slot[][], r: number): Slot[][] {
  const next = slots.map((row) => row.map((slot) => ({ ...slot })));
  const shrunk = new Set<string>();
  next[r].forEach((slot, c) => {
    if (slot.owner.r < r) {
      shrunk.add(`${slot.owner.r}:${slot.owner.c}`);
    } else if (slot.cell !== null) {
      const { cols, rows } = spanOf(slot.cell);
      if (rows > 1) {
        // The merge goes on from the next row, one row shorter.
        next[r + 1][c] = { cell: withSpan(slot.cell, cols, rows - 1), owner: { r: r + 1, c } };
        for (let dr = 1; dr < rows; dr += 1) {
          for (let dc = 0; dc < cols; dc += 1) {
            if (dr === 1 && dc === 0) continue;
            next[r + dr][c + dc] = { ...next[r + dr][c + dc], owner: { r: r + 1, c } };
          }
        }
      }
    }
  });
  for (const key of shrunk) {
    const [or, oc] = key.split(":").map(Number);
    const cell = next[or][oc].cell as Obj;
    const { cols, rows } = spanOf(cell);
    next[or][oc] = { ...next[or][oc], cell: withSpan(cell, cols, rows - 1) };
  }
  next.splice(r, 1);
  return next.map((row) => row.map((slot): Slot => (slot.owner.r > r ? { ...slot, owner: { r: slot.owner.r - 1, c: slot.owner.c } } : slot)));
}

/** Adds a blank row so it becomes row `at` (0 to the row count); inside the header it is a header row. */
export function addRow(shape: GridShape, at: number): GridResult {
  if (shape.rows.length >= MAX_GRID_ROWS) return { problem: "tooManyRows" };
  const dense = toDense(shape);
  const index = Math.max(0, Math.min(at, dense.slots.length));
  const slots = insertRowSlots(dense.slots, index);
  const meta = [...dense.meta.slice(0, index), {}, ...dense.meta.slice(index)];
  return { shape: fromDense({ ...dense, slots, meta, header: index < dense.header ? dense.header + 1 : dense.header }) };
}

/** Removes row `r`; the grid keeps at least one row. */
export function removeRow(shape: GridShape, r: number): GridResult {
  if (shape.rows.length <= 1) return { problem: "lastRow" };
  const dense = toDense(shape);
  const slots = removeRowSlots(dense.slots, r);
  const meta = dense.meta.filter((_, i) => i !== r);
  return { shape: fromDense({ ...dense, slots, meta, header: r < dense.header ? dense.header - 1 : dense.header }) };
}

/** Adds a blank column so it becomes column `at` (0 to the column count). */
export function addColumn(shape: GridShape, at: number): GridResult {
  if (shape.columns.length >= MAX_GRID_COLUMNS) return { problem: "tooManyColumns" };
  const dense = toDense(shape);
  const index = Math.max(0, Math.min(at, dense.columns.length));
  const slots = transpose(insertRowSlots(transpose(dense.slots), index));
  const columns = [...dense.columns.slice(0, index), {}, ...dense.columns.slice(index)];
  return { shape: fromDense({ ...dense, slots, columns }) };
}

/** Removes column `c`; the grid keeps at least one column. */
export function removeColumn(shape: GridShape, c: number): GridResult {
  if (shape.columns.length <= 1) return { problem: "lastColumn" };
  const dense = toDense(shape);
  const slots = transpose(removeRowSlots(transpose(dense.slots), c));
  return { shape: fromDense({ ...dense, slots, columns: dense.columns.filter((_, i) => i !== c) }) };
}

// ---- Reading -------------------------------------------------------------------------------------------------------

/** A cell's style once the cascade (cell, row, column, grid) is applied; `undefined` when nothing sets it. */
export interface EffectiveStyle {
  align: string;
  valign: string;
  fill?: string;
  color?: string;
  bold: boolean;
}

/** The style a cell is drawn with: its own value, else its row's, its first column's, the grid's, else the default. */
export function effectiveStyle(grid: Obj, shape: GridShape, at: GridPos): EffectiveStyle {
  const dense = toDense(shape);
  const owner = dense.slots[at.r]?.[at.c]?.owner ?? at;
  const layers: Obj[] = [dense.slots[owner.r]?.[owner.c]?.cell ?? {}, dense.meta[owner.r] ?? {}, dense.columns[owner.c] ?? {}, grid];
  const pick = <T>(key: GridStyleKey): T | undefined => {
    for (const layer of layers) if (layer[key] !== undefined) return layer[key] as T;
    return undefined;
  };
  const fill = pick<string>("fill");
  const color = pick<string>("color");
  return {
    align: pick<string>("align") ?? "left", valign: pick<string>("valign") ?? "top", bold: pick<boolean>("bold") ?? false,
    ...(fill !== undefined ? { fill } : {}), ...(color !== undefined ? { color } : {}),
  };
}

/** A short count of what the grid holds, for the block panel: columns, rows and merged cells. */
export function gridCounts(node: Obj): { columns: number; rows: number; merged: number } {
  const shape = shapeOf(node);
  const merged = placedCells(shape).filter((p) => p.rowspan > 1 || p.colspan > 1).length;
  return { columns: shape.columns.length, rows: shape.rows.length, merged };
}
