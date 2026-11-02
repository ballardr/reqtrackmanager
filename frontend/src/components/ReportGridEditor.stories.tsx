import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { buildColourContext } from "../testing/reportLayoutFixtures";
import { blankShape, type Obj } from "../utils/reportGrid";
import { ReportGridEditor, type GridDraft } from "./ReportGridEditor";
import { TextAreaField } from "./FormFields";

function Harness({ initial, readOnly = false, gridStyle }: { initial: GridDraft; readOnly?: boolean; gridStyle?: Obj }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <ReportGridEditor
        value={value} onChange={setValue} readOnly={readOnly} gridStyle={gridStyle} colours={buildColourContext()}
        renderCellText={(cell, onText, label) => <TextAreaField helpNotNeeded label={label} value={String(cell.text ?? "")} onChange={onText} />}
      />
      <output data-testid="value">{JSON.stringify(value)}</output>
    </>
  );
}

/** The custom table editor: select cells on the drawn grid, merge them, align and colour them, and add or remove rows and columns. */
const meta: Meta<typeof Harness> = { title: "Components/ReportGridEditor", component: Harness };
export default meta;

type Story = StoryObj<typeof Harness>;

const named = (row: number, column: number) => new RegExp(`^Row ${row}, column ${column}`);
const cell = (canvas: ReturnType<typeof within>, row: number, column: number) => canvas.getByLabelText(named(row, column));
const value = (canvas: ReturnType<typeof within>) => JSON.parse(canvas.getByTestId("value").textContent ?? "{}") as GridDraft;
const grid3x3 = (): GridDraft => {
  const shape = blankShape(3, 3);
  return { ...shape, rows: shape.rows.map((row, r) => ({ cells: (row.cells as object[]).map((_, c) => ({ text: `${r + 1}.${c + 1}` })) })) };
};

export const AnEmptyTableShowsDashedBlankCells: Story = {
  args: { initial: blankShape(2, 2) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("grid", { name: "Table cells" })).toBeVisible();
    await expect(canvas.getAllByRole("gridcell")).toHaveLength(4);
    await expect(cell(canvas, 1, 1)).toHaveTextContent("blank");
  },
};

export const ShiftClickSelectsARangeAndMergeJoinsIt: Story = {
  args: { initial: grid3x3() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // One user instance, so the held Shift key is still down for the second click.
    const user = userEvent.setup();
    await user.click(cell(canvas, 1, 1));
    await user.keyboard("{Shift>}");
    await user.click(cell(canvas, 2, 2));
    await user.keyboard("{/Shift}");
    await expect(canvas.getAllByRole("gridcell", { selected: true })).toHaveLength(4);
    await userEvent.click(canvas.getByRole("button", { name: "Merge cells" }));
    await expect(canvas.getAllByRole("gridcell")).toHaveLength(6);
    const merged = cell(canvas, 1, 1);
    await expect(merged).toHaveAttribute("aria-colspan", "2");
    await expect(merged).toHaveAttribute("aria-rowspan", "2");
    await expect(merged).toHaveTextContent("2 × 2");
    await expect(canvas.getByText("Cells merged.")).toBeVisible();
    await userEvent.click(canvas.getByRole("button", { name: "Unmerge cells" }));
    await expect(canvas.getAllByRole("gridcell")).toHaveLength(9);
  },
};

export const MergeIsOffForOneCellAndUnmergeForAnUnmergedSelection: Story = {
  args: { initial: grid3x3() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Merge cells" })).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "Unmerge cells" })).toBeDisabled();
  },
};

export const ArrowKeysMoveAndShiftArrowsExtendTheSelection: Story = {
  args: { initial: grid3x3() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const grid = canvas.getByRole("grid");
    grid.focus();
    await userEvent.keyboard("{ArrowRight}{ArrowDown}");
    await expect(canvas.getAllByRole("gridcell", { selected: true })).toHaveLength(1);
    await expect(cell(canvas, 2, 2)).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{Shift>}{ArrowRight}{ArrowDown}{/Shift}");
    await expect(canvas.getAllByRole("gridcell", { selected: true })).toHaveLength(4);
    await expect(grid).toHaveAttribute("aria-activedescendant", cell(canvas, 3, 3).id);
  },
};

export const AlignmentAppliesToTheSelectionAndShowsAsPressed: Story = {
  args: { initial: grid3x3() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(cell(canvas, 2, 2));
    await userEvent.click(canvas.getByRole("button", { name: "Align right" }));
    await expect(canvas.getByRole("button", { name: "Align right", pressed: true })).toBeVisible();
    await expect(canvas.getByRole("button", { name: "Align left", pressed: false })).toBeVisible();
    await userEvent.click(canvas.getByRole("button", { name: "Align to middle" }));
    await expect(value(canvas).rows[1].cells[1]).toEqual({ text: "2.2", align: "right", valign: "middle" });
    await userEvent.click(canvas.getByRole("button", { name: "Bold" }));
    await expect(value(canvas).rows[1].cells[1]).toMatchObject({ bold: true });
    await userEvent.click(canvas.getByRole("button", { name: "Bold" }));
    await expect(value(canvas).rows[1].cells[1]).toMatchObject({ bold: false });
  },
};

export const WholeColumnColoursAColumnInTwoClicks: Story = {
  args: { initial: grid3x3() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(cell(canvas, 1, 1));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Apply to" }), "columns");
    await userEvent.click(canvas.getByRole("button", { name: /^Fill:/ }));
    await userEvent.click(within(document.body).getByRole("button", { name: /^Black/ }));
    await expect(value(canvas).columns[0]).toEqual({ fill: "black" });
    // The cells of the column carry no value of their own, so the column's shows through.
    await expect(value(canvas).rows[2].cells[0]).toEqual({ text: "3.1" });
    await expect(cell(canvas, 3, 1)).toHaveStyle({ backgroundColor: "rgb(0, 0, 0)" });
    await expect(cell(canvas, 3, 2)).not.toHaveStyle({ backgroundColor: "rgb(0, 0, 0)" });
  },
};

export const AWholeRowCanBeColouredToo: Story = {
  args: { initial: grid3x3() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(cell(canvas, 2, 2));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Apply to" }), "rows");
    await userEvent.click(canvas.getByRole("button", { name: "Align centre" }));
    await expect(value(canvas).rows[1]).toMatchObject({ align: "center" });
  },
};

export const ALowContrastPairWarns: Story = {
  args: { initial: { ...grid3x3(), columns: [{ fill: "#222222", color: "#2a2a2a" }, {}, {}] } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("alert")).toHaveTextContent("hard to tell apart");
    await userEvent.click(cell(canvas, 1, 2));
    await expect(canvas.queryByRole("alert")).toBeNull();
  },
};

export const ABlackFillWithNoTextColourWarnsBecauseTheTextPrintsBlack: Story = {
  args: { initial: { ...grid3x3(), columns: [{ fill: "black" }, {}, {}] } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("alert")).toHaveTextContent("hard to tell apart");
    await userEvent.click(canvas.getByRole("button", { name: /^Text colour:/ }));
    await userEvent.click(within(document.body).getByRole("button", { name: /^White/ }));
    await expect(canvas.queryByRole("alert")).toBeNull();
  },
};

export const TheCellTextIsEditedInTheFieldUnderTheGrid: Story = {
  args: { initial: grid3x3() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(cell(canvas, 1, 2));
    const field = canvas.getByRole("textbox", { name: "Text of row 1, column 2" });
    await userEvent.clear(field);
    await userEvent.type(field, "Hello");
    await expect(cell(canvas, 1, 2)).toHaveTextContent("Hello");
    await expect(value(canvas).rows[0].cells[1]).toEqual({ text: "Hello" });
  },
};

export const EnterMovesFocusToTheCellText: Story = {
  args: { initial: grid3x3() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    canvas.getByRole("grid").focus();
    await userEvent.keyboard("{Enter}");
    await expect(canvas.getByRole("textbox", { name: "Text of row 1, column 1" })).toHaveFocus();
  },
};

export const RowsAndColumnsCanBeAddedAndRemoved: Story = {
  args: { initial: grid3x3() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(cell(canvas, 2, 2));
    await userEvent.click(canvas.getByRole("button", { name: "Add row below" }));
    await expect(canvas.getAllByRole("gridcell")).toHaveLength(12);
    await userEvent.click(canvas.getByRole("button", { name: "Add column right" }));
    await expect(canvas.getAllByRole("gridcell")).toHaveLength(16);
    await userEvent.click(canvas.getByRole("button", { name: "Remove row" }));
    await userEvent.click(canvas.getByRole("button", { name: "Remove column" }));
    await expect(canvas.getAllByRole("gridcell")).toHaveLength(9);
  },
};

export const TheLastRowAndColumnCannotBeRemoved: Story = {
  args: { initial: blankShape(1, 1) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Remove row" })).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "Remove column" })).toBeDisabled();
  },
};

export const RowHeightAndColumnWidthAreSetForTheSelectedCellsRowAndColumn: Story = {
  args: { initial: grid3x3() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(cell(canvas, 2, 3));
    await userEvent.type(canvas.getByRole("spinbutton", { name: "Height of row 2" }), "2");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Height unit" }), "mm");
    await userEvent.type(canvas.getByRole("textbox", { name: "Width of column 3" }), "30%");
    const draft = value(canvas);
    await expect(draft.rows[1]).toMatchObject({ height: 2, height_unit: "mm" });
    await expect(draft.columns[2]).toEqual({ width: "30%" });
  },
};

export const AColumnTakesItsOwnFontAndSizeAndInheritsWhenCleared: Story = {
  args: { initial: grid3x3() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(cell(canvas, 2, 2));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Font of column 2" }), "mono");
    await userEvent.type(canvas.getByRole("spinbutton", { name: "Size of column 2" }), "8");
    await expect(value(canvas).columns[1]).toEqual({ font: "mono", size: 8 });
    await expect(value(canvas).columns[0]).toEqual({});
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Font of column 2" }), "");
    await userEvent.clear(canvas.getByRole("spinbutton", { name: "Size of column 2" }));
    await expect(value(canvas).columns[1]).toEqual({});
  },
};

export const AMergeAcrossTheHeaderIsRefusedWithAReason: Story = {
  args: { initial: { ...grid3x3(), header_rows: 1 } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const user = userEvent.setup();
    await user.click(cell(canvas, 1, 1));
    await user.keyboard("{Shift>}");
    await user.click(cell(canvas, 2, 1));
    await user.keyboard("{/Shift}");
    await user.click(canvas.getByRole("button", { name: "Merge cells" }));
    await expect(canvas.getByRole("alert")).toHaveTextContent("cannot run from the header rows");
    await expect(canvas.getAllByRole("gridcell")).toHaveLength(6);
    await expect(canvas.getAllByRole("columnheader")).toHaveLength(3);
  },
};

export const LongTextWrapsInsideItsCell: Story = {
  args: { initial: { ...grid3x3(), rows: [{ cells: [{ text: "A very long sentence ".repeat(30) }, { text: "b" }, { text: "c" }] }] } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const first = cell(canvas, 1, 1);
    await expect(first.scrollWidth).toBeLessThanOrEqual(first.clientWidth + 1);
  },
};

export const ReadOnlyShowsTheGridWithoutControls: Story = {
  args: { initial: grid3x3(), readOnly: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button", { name: "Merge cells" })).toBeNull();
    await expect(canvas.getAllByRole("gridcell")).toHaveLength(9);
  },
};

/** The selection how-to is behind a (?) in the structure toolbar, not a paragraph above the grid. */
export const TheSelectionHintIsBehindAHelpButton: Story = {
  args: { initial: blankShape(2, 2) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByText(/Shift\+click or Shift\+arrow keys/)).not.toBeInTheDocument();
    canvas.getByRole("button", { name: "Help: Selecting cells" }).focus();
    await expect(await within(document.body).findByRole("tooltip", { hidden: true })).toHaveTextContent(/Shift\+click/);
  },
};
