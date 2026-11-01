import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import {
  addColumn, addRow, blankShape, canMerge, cellAt, effectiveStyle, gridCounts, headerRowsProblem, mergeCells, ownerOf, placedCells, removeColumn,
  removeRow, selectionRect, setHeaderRows, setRowHeight, shapeOf, styleCells, styleColumns, styleRows, unmergeCells, type GridResult, type GridShape,
} from "./reportGrid";

/** The pure model behind the custom table editor, exercised as plain functions (the stories render nothing). */
const meta: Meta = { title: "Utils/reportGrid", render: () => <p>Pure helpers; see the interactions.</p> };
export default meta;

type Story = StoryObj;

const texts = (shape: GridShape) => shape.rows.map((row) => (row.cells as { text: string }[]).map((c) => c.text));
const must = (result: GridResult): GridShape => {
  if ("problem" in result) throw new Error(`refused: ${result.problem}`);
  return result.shape;
};
/** A 3 x 3 grid whose cells read "r,c". */
function numbered(): GridShape {
  const shape = blankShape(3, 3);
  return { ...shape, rows: shape.rows.map((row, r) => ({ cells: (row.cells as object[]).map((_, c) => ({ text: `${r},${c}` })) })) };
}

export const MergingKeepsTheTopLeftCellAndJoinsTheText: Story = {
  play: async () => {
    const merged = must(mergeCells(numbered(), { r0: 0, c0: 0, r1: 1, c1: 1 }));
    await expect(merged.rows[0].cells).toEqual([{ text: "0,0\n0,1\n1,0\n1,1", colspan: 2, rowspan: 2 }, { text: "0,2" }]);
    // The covered positions are left out: row 1 lists only the cell at column 2.
    await expect(texts(merged)[1]).toEqual(["1,2"]);
    await expect(gridCounts({ ...merged })).toEqual({ columns: 3, rows: 3, merged: 1 });
  },
};

export const UnmergingRestoresSingleCellsThatCopyTheStyle: Story = {
  play: async () => {
    const styled = styleCells(numbered(), { r0: 0, c0: 0, r1: 0, c1: 0 }, { fill: "black" });
    const merged = must(mergeCells(styled, { r0: 0, c0: 0, r1: 0, c1: 1 }));
    const split = unmergeCells(merged, { r0: 0, c0: 0, r1: 0, c1: 1 });
    await expect(split.rows[0].cells).toEqual([{ text: "0,0\n0,1", fill: "black" }, { text: "", fill: "black" }, { text: "0,2" }]);
    await expect(placedCells(split).every((p) => p.colspan === 1 && p.rowspan === 1)).toBe(true);
  },
};

export const ASelectionIsWidenedToHoldWholeMergedCells: Story = {
  play: async () => {
    const merged = must(mergeCells(numbered(), { r0: 0, c0: 0, r1: 1, c1: 1 }));
    // Selecting only the covered position (1,1) selects the whole 2 x 2 cell.
    await expect(selectionRect(merged, { r: 1, c: 1 }, { r: 1, c: 1 })).toEqual({ r0: 0, c0: 0, r1: 1, c1: 1 });
    // A range reaching into the merge takes all of it.
    await expect(selectionRect(merged, { r: 1, c: 2 }, { r: 2, c: 1 })).toEqual({ r0: 0, c0: 0, r1: 2, c1: 2 });
    await expect(ownerOf(merged, { r: 1, c: 1 })).toEqual({ r: 0, c: 0 });
  },
};

export const MergingNeedsTwoCellsAndMayNotCrossTheHeader: Story = {
  play: async () => {
    await expect(canMerge(numbered(), { r0: 0, c0: 0, r1: 0, c1: 0 })).toEqual({ problem: "nothingToMerge" });
    const withHeader = { ...numbered(), header_rows: 1 };
    await expect(mergeCells(withHeader, { r0: 0, c0: 0, r1: 1, c1: 0 })).toEqual({ problem: "acrossHeader" });
    await expect("shape" in mergeCells(withHeader, { r0: 1, c0: 0, r1: 2, c1: 0 })).toBe(true);
    // The header cannot be set where a merge already crosses it.
    const merged = must(mergeCells(numbered(), { r0: 0, c0: 0, r1: 1, c1: 0 }));
    await expect(headerRowsProblem(merged, 1)).toBe("acrossHeader");
    await expect(setHeaderRows(merged, 2)).toEqual({ shape: { ...merged, header_rows: 2 } });
  },
};

export const AddingARowInsideAMergeStretchesTheMerge: Story = {
  play: async () => {
    const merged = must(mergeCells(numbered(), { r0: 0, c0: 0, r1: 1, c1: 1 }));
    const grown = must(addRow(merged, 1));
    await expect(grown.rows).toHaveLength(4);
    await expect(grown.rows[0].cells[0]).toMatchObject({ colspan: 2, rowspan: 3 });
    // The new row has a cell only where nothing from above covers it.
    await expect(texts(grown)[1]).toEqual([""]);
    await expect(texts(grown)[2]).toEqual(["1,2"]);
  },
};

export const AddingARowAtTheEdgesOfAMergeLeavesItAlone: Story = {
  play: async () => {
    const merged = must(mergeCells(numbered(), { r0: 0, c0: 0, r1: 1, c1: 1 }));
    await expect(must(addRow(merged, 0)).rows[1].cells[0]).toMatchObject({ colspan: 2, rowspan: 2 });
    await expect(must(addRow(merged, 2)).rows[0].cells[0]).toMatchObject({ colspan: 2, rowspan: 2 });
    await expect(texts(must(addRow(merged, 2)))[2]).toEqual(["", "", ""]);
  },
};

export const AddingAColumnInsideAMergeStretchesIt: Story = {
  play: async () => {
    const merged = must(mergeCells(numbered(), { r0: 0, c0: 0, r1: 1, c1: 1 }));
    const grown = must(addColumn(merged, 1));
    await expect(grown.columns).toHaveLength(4);
    await expect(grown.rows[0].cells[0]).toMatchObject({ colspan: 3, rowspan: 2 });
    await expect(texts(grown)[2]).toEqual(["2,0", "", "2,1", "2,2"]);
  },
};

export const RemovingARowThatStartsAMergeMovesItDown: Story = {
  play: async () => {
    const merged = must(mergeCells(numbered(), { r0: 0, c0: 0, r1: 1, c1: 1 }));
    const shorter = must(removeRow(merged, 0));
    await expect(shorter.rows).toHaveLength(2);
    await expect(shorter.rows[0].cells[0]).toMatchObject({ colspan: 2 });
    await expect(shorter.rows[0].cells[0]).not.toHaveProperty("rowspan");
    await expect(shorter.rows[0].cells).toHaveLength(2);
  },
};

export const RemovingARowInsideAMergeShrinksIt: Story = {
  play: async () => {
    const merged = must(mergeCells(numbered(), { r0: 0, c0: 0, r1: 2, c1: 0 }));
    const shorter = must(removeRow(merged, 1));
    await expect(shorter.rows[0].cells[0]).toMatchObject({ rowspan: 2 });
    await expect(shorter.rows).toHaveLength(2);
    await expect(texts(shorter)[1]).toEqual(["2,1", "2,2"]);
  },
};

export const RemovingAColumnWorksLikeRemovingARow: Story = {
  play: async () => {
    const merged = must(mergeCells(numbered(), { r0: 0, c0: 0, r1: 0, c1: 1 }));
    const shorter = must(removeColumn(merged, 0));
    await expect(shorter.columns).toHaveLength(2);
    await expect(shorter.rows[0].cells[0]).not.toHaveProperty("colspan");
    await expect(texts(shorter)[0]).toEqual(["0,0\n0,1", "0,2"]);
    await expect(texts(shorter)[1]).toEqual(["1,1", "1,2"]);
  },
};

export const TheGridKeepsOneRowAndOneColumnAndStaysWithinTheLimits: Story = {
  play: async () => {
    await expect(removeRow(blankShape(1, 2), 0)).toEqual({ problem: "lastRow" });
    await expect(removeColumn(blankShape(2, 1), 0)).toEqual({ problem: "lastColumn" });
    await expect(addRow(blankShape(200, 1), 0)).toEqual({ problem: "tooManyRows" });
    await expect(addColumn(blankShape(1, 20), 0)).toEqual({ problem: "tooManyColumns" });
  },
};

export const ARowAddedInsideTheHeaderIsAHeaderRow: Story = {
  play: async () => {
    const header = { ...numbered(), header_rows: 2 };
    await expect(must(addRow(header, 1)).header_rows).toBe(3);
    await expect(must(addRow(header, 2)).header_rows).toBe(2);
    await expect(must(removeRow(header, 0)).header_rows).toBe(1);
  },
};

export const AColumnStyleClearsTheCellsOwnValueSoItShows: Story = {
  play: async () => {
    const own = styleCells(numbered(), { r0: 1, c0: 0, r1: 1, c1: 0 }, { fill: "white" });
    const shape = styleColumns(own, 0, 0, { fill: "black", color: "white", bold: true });
    await expect(shape.columns[0]).toEqual({ fill: "black", color: "white", bold: true });
    await expect(cellAt(shape, { r: 1, c: 0 })).toEqual({ text: "1,0" });
    await expect(effectiveStyle({}, shape, { r: 1, c: 0 })).toMatchObject({ fill: "black", color: "white", bold: true });
    await expect(effectiveStyle({}, shape, { r: 1, c: 1 }).fill).toBeUndefined();
  },
};

export const TheCascadeRunsCellRowColumnGrid: Story = {
  play: async () => {
    let shape = styleColumns(numbered(), 1, 1, { align: "right", fill: "#111111" });
    shape = styleRows(shape, 1, 1, { align: "center" });
    shape = styleCells(shape, { r0: 1, c0: 1, r1: 1, c1: 1 }, { align: "justify" });
    const grid = { align: "left", valign: "bottom", color: "#222222" };
    await expect(effectiveStyle(grid, shape, { r: 0, c: 1 })).toMatchObject({ align: "right", fill: "#111111", valign: "bottom", color: "#222222" });
    await expect(effectiveStyle(grid, shape, { r: 1, c: 0 }).align).toBe("center");
    await expect(effectiveStyle(grid, shape, { r: 1, c: 1 }).align).toBe("justify");
    await expect(effectiveStyle(grid, shape, { r: 2, c: 2 })).toMatchObject({ align: "left", bold: false });
  },
};

export const ClearingAStyleFallsBackToWhatTheCascadeSays: Story = {
  play: async () => {
    const set = styleCells(numbered(), { r0: 0, c0: 0, r1: 0, c1: 0 }, { align: "right" });
    await expect(cellAt(set, { r: 0, c: 0 })).toEqual({ text: "0,0", align: "right" });
    await expect(cellAt(styleCells(set, { r0: 0, c0: 0, r1: 0, c1: 0 }, { align: undefined }), { r: 0, c: 0 })).toEqual({ text: "0,0" });
  },
};

export const ARowHeightIsAMinimumInCmOrMm: Story = {
  play: async () => {
    const tall = setRowHeight(numbered(), 1, 2, "cm");
    await expect(tall.rows[1]).toMatchObject({ height: 2 });
    await expect(tall.rows[1]).not.toHaveProperty("height_unit");
    await expect(setRowHeight(tall, 1, 25, "mm").rows[1]).toMatchObject({ height: 25, height_unit: "mm" });
    await expect(setRowHeight(tall, 1, undefined, "cm").rows[1]).not.toHaveProperty("height");
  },
};

export const AShortOrOverlongTreeIsNormalisedOnTheFirstEdit: Story = {
  play: async () => {
    const short = shapeOf({ columns: [{}, {}, {}], rows: [{ cells: [{ text: "a" }] }, { cells: [{ text: "b" }, { text: "c" }, { text: "d" }, { text: "e" }] }] });
    const edited = styleCells(short, { r0: 0, c0: 0, r1: 0, c1: 0 }, { bold: true });
    await expect(texts(edited)).toEqual([["a", "", ""], ["b", "c", "d"]]);
  },
};
