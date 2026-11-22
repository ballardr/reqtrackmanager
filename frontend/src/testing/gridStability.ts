/**
 * Module: testing/gridStability
 *
 * The shared "does long text move its neighbours?" assertion for every grid and table-like view. A grid that
 * looks tidy with a short demo name can lose its shape when a row holds a 200-character name or a 60-character
 * word with no space: a column widens, a description wraps and drops its Edit button onto a second line, a
 * right-hand text no longer lines up. A tidy story never shows it. This reads the real layout and returns what
 * is wrong, so Storybook play functions and Playwright specs fail instead of someone spotting it in a
 * screenshot. It extends `orphanedControls` (a control alone on a wrapped line) from one flex row to the whole
 * grid.
 *
 * Self-contained on purpose (no imports, helpers inside each function) so Playwright can ship it into the
 * page with `page.evaluate`, the same as `controlGeometry`.
 *
 * Grids and tables checked: `.definition-grid`, `table`, `[role=grid]`, `[role=treegrid]`, `.directory-table`, `.tile-grid` and `.aligned-rows`; a
 * row layout built from flex (an item row, an aligned list, a settings row: `ROW_SELECTOR`) is checked for rules 2
 * and 3 and for its last control lining up with its siblings', and any other opts in with `data-stress-row`. An
 * element with `data-wrap-ok` (or inside one) is skipped, for a row that is meant to wrap.
 *
 * Rules, per grid:
 * 1. the cells of one column share a left edge in every row, and so do the controls inside them (the first
 *    button of each row's cell, the second...) when the cells hold the same number of controls;
 * 2. the controls of one row (`button`, `a`, `input`, `select`, `textarea`) each have their vertical centre
 *    within the span of the row's tallest control, so none has dropped to a second line;
 * 3. no cell is wider than its column and nothing overflows the grid horizontally; text clipped by an
 *    `overflow: hidden` ancestor inside its cell (an ellipsis, `CellText`) is allowed;
 * 4. (`layoutChanges`, between a short-text and a long-text render) the column widths are the same, for
 *    a CSS grid or a fixed-layout table, and long text does not make the grid scroll sideways when short text
 *    did not (a table in a scrolling wrapper is allowed to scroll when it is wide by design, not because one
 *    cell held a long word). An auto-layout table sizes its columns from its text by design; its harm is
 *    overflow, which rule 3 and the scroll comparison catch.
 */

/** One grid as drawn. */
export interface GridMeasurement {
  /** Short DOM path to the grid, to locate it in a report. */
  label: string;
  /** Whether the grid's column widths are meant to be independent of its text (rule 4 applies). */
  fixedColumns: boolean;
  /** Width of each column, in pixels (empty when the grid has no column structure). */
  columnWidths: number[];
  /** Whether the grid's container has to scroll sideways to show it (a table in a scrolling wrapper). */
  scrollsSideways: boolean;
}

/** What `gridLayout` reports. */
export interface GridLayout {
  grids: GridMeasurement[];
  /** How many flex row layouts (`ROW_SELECTOR`) were checked; a view with no grid has these. */
  rowsChecked: number;
  violations: string[];
}

/**
 * Measures every grid and table under `root` and lists what is wrong with its layout (rules 1 to 3).
 *
 * @param root Element to search; defaults to the whole document.
 * @returns One measurement per grid in document order, and the human-readable violations (empty when every
 *     grid keeps its shape).
 */
export function gridLayout(root?: Element): GridLayout {
  const scope: ParentNode = root ?? document;
  const round = (n: number) => Math.round(n * 10) / 10;
  const describe = (el: Element): string => {
    const parts: string[] = [];
    let node: Element | null = el;
    for (let depth = 0; node && depth < 3 && node !== document.body; depth += 1) {
      const cls = (node.getAttribute("class") ?? "").split(/\s+/).filter(Boolean)[0];
      parts.unshift(node.tagName.toLowerCase() + (cls ? `.${cls}` : ""));
      node = node.parentElement;
    }
    return parts.join(" > ");
  };
  const drawn = (el: Element) => {
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && getComputedStyle(el).visibility !== "hidden";
  };
  const text = (el: Element) => (el.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 40);
  /** The children of `el`, looking through `display: contents` wrappers (a grid row that only groups its cells). */
  const flatChildren = (el: Element): HTMLElement[] =>
    (Array.from(el.children) as HTMLElement[]).flatMap((child) =>
      getComputedStyle(child).display === "contents" ? flatChildren(child) : [child]);
  /** The controls whose vertical centre is outside the span of the row's tallest control (one that left its line). */
  const offLine = (controls: HTMLElement[]): HTMLElement[] => {
    if (controls.length < 2) return [];
    const boxes = controls.map((el) => el.getBoundingClientRect());
    const tallest = boxes.reduce((a, b) => (b.height > a.height ? b : a));
    return controls.filter((_, index) => {
      const centre = (boxes[index].top + boxes[index].bottom) / 2;
      return centre < tallest.top - 1 || centre > tallest.bottom + 1;
    });
  };
  const CONTROLS = "button, a[href], input, select, textarea";
  /** Row layouts checked beside the grids; `data-stress-row` opts any other row in. */
  const ROW_SELECTOR = "[data-stress-row], .module-settings-main, .item-list-row, .item-row";

  const violations: string[] = [];
  const grids: GridMeasurement[] = [];
  const found = Array.from(
    scope.querySelectorAll<HTMLElement>(".definition-grid, table, [role=grid], [role=treegrid], .directory-table, .tile-grid, .aligned-rows"),
  ).filter((el) => !el.closest("[data-wrap-ok]") && drawn(el));
  // A `.directory-table` that is itself a `table` is one grid.
  const unique = found.filter((el, index) => found.indexOf(el) === index);

  unique.forEach((grid) => {
    const label = describe(grid);
    const style = getComputedStyle(grid);
    const isTable = grid.tagName === "TABLE";
    const isCssGrid = style.display.includes("grid");
    const gridRect = grid.getBoundingClientRect();

    // Cells and rows.
    let rows: HTMLElement[][];
    let rowElements: HTMLElement[];
    let subgridRows = false;
    if (isTable) {
      rowElements = Array.from((grid as HTMLTableElement).rows);
      rows = rowElements.map((row) => Array.from((row as HTMLTableRowElement).cells));
    } else if (isCssGrid) {
      // The tracks give the rows: a cell's row is the set of cells that share a top track; here, the cells
      // in document order cut into rows of `columns` cells.
            const flat = flatChildren(grid).filter(drawn);
      if (flat.length > 0 && flat.every((child) => child.getAttribute("role") === "row")) {
        // Rows that are subgrids of the grid (a tree grid): each child is a row and its children are the cells.
        rows = flat.map((row) => flatChildren(row).filter(drawn));
        rowElements = flat;
        subgridRows = true;
      } else {
        // The cells of one row are the cells whose vertical centre falls in the same row track.
        const gap = parseFloat(style.rowGap) || 0;
        const heights = style.gridTemplateRows.split(" ").map(parseFloat).filter((n) => Number.isFinite(n));
        let top = gridRect.top + (parseFloat(style.paddingTop) || 0) + (parseFloat(style.borderTopWidth) || 0);
        const bands = heights.map((height) => { const band = { top, bottom: top + height }; top += height + gap; return band; });
        const byBand = new Map<number, HTMLElement[]>();
        flat.forEach((cell) => {
          const box = cell.getBoundingClientRect();
          const centre = (box.top + box.bottom) / 2;
          const index = Math.max(0, bands.findIndex((band) => centre >= band.top - 1 && centre <= band.bottom + 1));
          byBand.set(index, [...(byBand.get(index) ?? []), cell]);
        });
        rows = Array.from(byBand.keys()).sort((a, b) => a - b).map((index) => byBand.get(index) ?? []);
        rowElements = rows.map((row) => row[0]?.parentElement ?? grid);
      }
    } else {
      rowElements = flatChildren(grid);
      rows = rowElements.map((row) => flatChildren(row));
    }

    // Column widths (rule 4) and expected left edges (rule 1).
    let columnWidths: number[] = [];
    let starts: number[] = [];
    if (isCssGrid && !isTable && !subgridRows) {
      const gap = parseFloat(style.columnGap) || 0;
      const tracks = style.gridTemplateColumns.split(" ").map(parseFloat).filter((n) => Number.isFinite(n));
      columnWidths = tracks.map(round);
      let left = gridRect.left + (parseFloat(style.paddingLeft) || 0) + (parseFloat(style.borderLeftWidth) || 0);
      starts = tracks.map((width) => { const start = left; left += width + gap; return start; });
    } else if (isTable || subgridRows) {
      const first = rows.find((cells) => cells.length > 0 && cells.every((cell) => ((cell as HTMLTableCellElement).colSpan ?? 1) === 1));
      columnWidths = first ? first.map((cell) => round(cell.getBoundingClientRect().width)) : [];
    }
    const wrapper = grid.parentElement;
    const scrollsSideways = grid.scrollWidth > grid.clientWidth + 1
      || (!!wrapper && wrapper.scrollWidth > wrapper.clientWidth + 1);
    grids.push({ label, fixedColumns: isCssGrid || (isTable && style.tableLayout === "fixed"), columnWidths, scrollsSideways });

    // Rule 1: the cells of a column share a left edge.
    if (starts.length) {
      rows.forEach((cells) => cells.forEach((cell) => {
        const left = cell.getBoundingClientRect().left;
        if (!starts.some((start) => Math.abs(start - left) <= 1.5)) {
          violations.push(`${label}: "${text(cell)}" starts at ${round(left)}px, which is no column's left edge`);
        }
      }));
    } else if (isTable || subgridRows) {
      // A table, or rows that are subgrids with a padding of their own: a column is compared with itself in
      // the other rows. A row with a different number of cells (an empty-folder note) has no columns to compare.
      const reference = new Map<number, number>();
      const full = Math.max(...rows.map((cells) => cells.length));
      rows.forEach((cells) => {
        if (cells.some((cell) => ((cell as HTMLTableCellElement).colSpan ?? 1) > 1)) return;
        if (subgridRows && cells.length !== full) return;
        cells.forEach((cell, column) => {
          const left = cell.getBoundingClientRect().left;
          const known = reference.get(column);
          if (known === undefined) reference.set(column, left);
          else if (Math.abs(known - left) > 1.5) {
            violations.push(`${label}: column ${column + 1} starts at ${round(known)}px in one row and ${round(left)}px in another`);
          }
        });
      });
    }

    // Rule 1b: the same control (the first, the second...) of a column's cells lines up down the column, when each
    // cell holds the same number of controls, so a text of a different length does not move the buttons after it.
    const lefts = new Map<string, { left: number; text: string }[]>();
    const fullRow = Math.max(...rows.map((cells) => cells.length));
    rows.forEach((cells) => cells.forEach((cell, index) => {
      const column = starts.length
        ? starts.findIndex((start) => Math.abs(start - cell.getBoundingClientRect().left) <= 1.5)
        : (cells.length === fullRow ? index : -1);
      if (column < 0) return;
      // A heading's sort button fills its cell's padding, so it is not compared with the controls of the body.
      if (cell.matches("th, [role=columnheader]")) return;
      const inside = Array.from(cell.querySelectorAll<HTMLElement>(CONTROLS)).filter((el) => drawn(el) && !el.closest("[data-wrap-ok]"));
      inside.forEach((control, order) => {
        const key = `${column}:${inside.length}:${order}`;
        lefts.set(key, [...(lefts.get(key) ?? []), { left: control.getBoundingClientRect().left, text: control.getAttribute("aria-label") ?? text(control) }]);
      });
    }));
    lefts.forEach((group, key) => {
      const min = Math.min(...group.map((entry) => entry.left));
      const max = Math.max(...group.map((entry) => entry.left));
      if (group.length > 1 && max - min > 1.5) {
        violations.push(`${label}: the controls of column ${Number(key.split(":")[0]) + 1} do not line up (their left edges differ by ${round(max - min)}px, for example "${group[0].text}")`);
      }
    });

    // Rule 2: the controls of a row stay on one line.
    const rowsToCheck = grid.matches(".tile-grid")
      // A tile holds several rows (a heading line, then a body, then a footer); only its heading line is one row.
      ? Array.from(grid.querySelectorAll<HTMLElement>(".tile-card-head")).map((head) => [head, ...Array.from(head.querySelectorAll<HTMLElement>("*"))])
      : isCssGrid && !isTable
      ? rows.map((cells) => cells.flatMap((cell) => [cell, ...Array.from(cell.querySelectorAll<HTMLElement>("*"))]))
      : rowElements.map((row) => [row, ...Array.from(row.querySelectorAll<HTMLElement>("*"))]);
    rowsToCheck.forEach((elements) => {
      const controls = elements.filter((el) => el.matches(CONTROLS) && drawn(el) && !el.closest("[data-wrap-ok]"));
      offLine(controls).forEach((control) => {
        violations.push(`${label}: control "${control.getAttribute("aria-label") ?? text(control)}" is on a second line of its row`);
      });
    });
    // Rule 3: nothing overflows the grid, and no cell's content sticks out of the cell unclipped.
    if (grid.scrollWidth > grid.clientWidth + 1) {
      violations.push(`${label}: content is ${grid.scrollWidth}px wide in a ${grid.clientWidth}px grid (horizontal overflow)`);
    }
    const container = grid.parentElement;
    if (container && !["auto", "scroll"].includes(getComputedStyle(container).overflowX) && container.scrollWidth > container.clientWidth + 1) {
      violations.push(`${label}: its container is ${container.scrollWidth}px wide in ${container.clientWidth}px (horizontal overflow)`);
    }
    const cellsToCheck = rows.flat();
    cellsToCheck.forEach((cell) => {
      const cellRect = cell.getBoundingClientRect();
      if (cellRect.right > gridRect.right + 1) {
        violations.push(`${label}: "${text(cell)}" ends at ${round(cellRect.right)}px, past the grid's edge at ${round(gridRect.right)}px`);
      }
      // Text placed straight in the cell (no element around it) that is wider than the cell and not clipped by it.
      if (cell.scrollWidth > cell.clientWidth + 1 && getComputedStyle(cell).overflowX === "visible") {
        violations.push(`${label}: "${text(cell)}" is ${cell.scrollWidth}px wide in a ${cell.clientWidth}px cell`);
      }
      cell.querySelectorAll<HTMLElement>("*").forEach((el) => {
        if (!drawn(el)) return;
        const rect = el.getBoundingClientRect();
        if (rect.right <= cellRect.right + 1) return;
        for (let node: HTMLElement | null = el.parentElement; node; node = node.parentElement) {
          if (getComputedStyle(node).overflowX !== "visible") return; // clipped inside the cell
          if (node === cell) break;
        }
        violations.push(`${label}: ${describe(el)} "${text(el)}" sticks out of its cell by ${round(rect.right - cellRect.right)}px`);
      });
    });
  });

  // Row layouts built from flex (an item row, an aligned list, a settings row): not a grid, but the same defects
  // apply, so each is checked for rules 2 and 3, and the controls at the end of sibling rows must line up.
  let rowsChecked = 0;
  const lastRight = new Map<Element, { row: HTMLElement; right: number }[]>();
  scope.querySelectorAll<HTMLElement>(ROW_SELECTOR).forEach((row) => {
    if (row.closest("[data-wrap-ok]") || !drawn(row)) return;
    rowsChecked += 1;
    const controls = Array.from(row.querySelectorAll<HTMLElement>(CONTROLS)).filter((el) => drawn(el) && !el.closest("[data-wrap-ok]"));
    const boxes = controls.map((el) => el.getBoundingClientRect());
    offLine(controls).forEach((control) => {
      violations.push(`${describe(row)}: control "${control.getAttribute("aria-label") ?? text(control)}" is on a second line of its row`);
    });
    if (row.scrollWidth > row.clientWidth + 1 && getComputedStyle(row).overflowX === "visible") {
      violations.push(`${describe(row)}: "${text(row)}" is ${row.scrollWidth}px wide in a ${row.clientWidth}px row`);
    }
    const parent = row.closest("ul, ol") ?? row.parentElement;
    if (parent && boxes.length > 0) {
      const group = lastRight.get(parent) ?? [];
      group.push({ row, right: Math.max(...boxes.map((box) => box.right)) });
      lastRight.set(parent, group);
    }
  });
  lastRight.forEach((group) => {
    const first = group[0];
    group.forEach((entry) => {
      if (Math.abs(entry.right - first.right) > 1.5) {
        violations.push(`${describe(entry.row)}: its last control ends at ${round(entry.right)}px, not ${round(first.right)}px like the row above`);
      }
    });
  });

  return { grids, rowsChecked, violations };
}

/** Violations only (rules 1 to 3), for Storybook play functions. */
export function gridLayoutViolations(root?: Element): string[] {
  return gridLayout(root).violations;
}

/**
 * Rule 4: compares the grids of a short-text render with the same grids of a long-text render.
 *
 * @param short The measurement of the short-text render (`gridLayout(...).grids`).
 * @param long The measurement of the long-text render, in the same order.
 * @param tolerancePx How many pixels a column may differ by (default 1).
 * @returns One message per column whose width moved and per grid that began to scroll sideways; grids whose
 *     columns follow their text are skipped for the column comparison.
 */
export function layoutChanges(short: GridMeasurement[], long: GridMeasurement[], tolerancePx = 1): string[] {
  const problems: string[] = [];
  if (short.length !== long.length) {
    problems.push(`the short-text render has ${short.length} grids and the long-text render ${long.length}`);
    return problems;
  }
  short.forEach((before, index) => {
    const after = long[index];
    if (after.scrollsSideways && !before.scrollsSideways) {
      problems.push(`${after.label}: long text makes it scroll sideways`);
    }
    if (!before.fixedColumns || !after.fixedColumns) return;
    if (before.columnWidths.length !== after.columnWidths.length) {
      problems.push(`${after.label}: ${before.columnWidths.length} columns with short text, ${after.columnWidths.length} with long text`);
      return;
    }
    before.columnWidths.forEach((width, column) => {
      if (Math.abs(width - after.columnWidths[column]) > tolerancePx) {
        problems.push(`${after.label}: column ${column + 1} is ${width}px with short text and ${after.columnWidths[column]}px with long text`);
      }
    });
  });
  return problems;
}
