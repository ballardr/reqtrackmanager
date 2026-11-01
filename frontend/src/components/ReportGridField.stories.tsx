import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildColourContext } from "../testing/reportLayoutFixtures";
import type { Obj } from "../utils/reportGrid";
import { TextAreaField } from "./FormFields";
import { ReportGridField, type GridPatch } from "./ReportGridField";

const TABLE: Obj = {
  type: "grid", columns: [{}, {}], header_rows: 1,
  rows: [{ cells: [{ text: "Document", bold: true }, { text: "{{report_title}}" }] }, { cells: [{ text: "Reviewed by" }, { text: "" }] }],
};

function Harness({ initial = TABLE, disabled = false }: { initial?: Obj; disabled?: boolean }) {
  const [node, setNode] = useState<Obj>(initial);
  return (
    <>
      <ReportGridField
        label="Table" node={node} disabled={disabled} colours={buildColourContext()}
        onSave={(patch: GridPatch) => setNode({ ...node, columns: patch.columns, rows: patch.rows, header_rows: patch.header_rows })}
        renderCellText={(cell, onText, label) => <TextAreaField helpNotNeeded label={label} value={String(cell.text ?? "")} onChange={onText} />}
      />
      <output data-testid="node">{JSON.stringify(node)}</output>
    </>
  );
}

/** The block panel's custom table control: a read-only summary and an Edit table button that opens the editor in a dialog. */
const meta: Meta<typeof Harness> = { title: "Components/ReportGridField", component: Harness };
export default meta;

type Story = StoryObj<typeof Harness>;

const node = (canvas: ReturnType<typeof within>) => JSON.parse(canvas.getByTestId("node").textContent ?? "{}") as Obj & { rows: { cells: Obj[] }[] };
const dialog = () => within(document.body).getByRole("dialog", { name: "Edit custom table" });

export const ThePanelShowsOnlyASummary: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByTestId("grid-summary")).toHaveTextContent("2 columns · 2 rows");
    await expect(canvas.queryByRole("grid")).toBeNull();
    await expect(canvas.getByRole("button", { name: "Edit table" })).toBeVisible();
  },
};

export const TheSummaryCountsMergedCells: Story = {
  args: { initial: { ...TABLE, rows: [{ cells: [{ text: "Title", colspan: 2 }] }, { cells: [{ text: "a" }, { text: "b" }] }] } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByTestId("grid-summary")).toHaveTextContent("2 columns · 2 rows · 1 merged");
  },
};

export const EditTableOpensTheGridInADialogWithSaveAndCancelInItsHeader: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Edit table" }));
    const body = dialog();
    await expect(within(body).getByRole("grid", { name: "Table cells" })).toBeVisible();
    await expect(within(body).getByRole("button", { name: "Save" })).toBeVisible();
    await expect(within(body).getByRole("button", { name: "Cancel" })).toBeVisible();
  },
};

export const SaveHandsBackColumnsRowsAndTheHeaderCountTogether: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Edit table" }));
    const body = within(dialog());
    await userEvent.click(body.getByLabelText(/^Row 2, column 2/));
    await userEvent.type(body.getByRole("textbox", { name: "Text of row 2, column 2" }), "Ann");
    await userEvent.click(body.getByRole("button", { name: "Add row below" }));
    await userEvent.click(body.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(canvas.getByTestId("grid-summary")).toHaveTextContent("3 rows"));
    await expect(node(canvas).rows[1].cells[1]).toEqual({ text: "Ann" });
    await expect(node(canvas).header_rows).toBe(1);
    await expect(canvas.queryByRole("dialog")).toBeNull();
  },
};

export const CancelDiscardsEveryChange: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Edit table" }));
    const body = within(dialog());
    await userEvent.click(body.getByRole("button", { name: "Add column right" }));
    await userEvent.click(body.getByRole("button", { name: "Cancel" }));
    await expect(canvas.getByTestId("grid-summary")).toHaveTextContent("2 columns");
    await expect(node(canvas).columns).toHaveLength(2);
  },
};

export const UndoAndRedoStepThroughTheDraft: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Edit table" }));
    const body = within(dialog());
    await expect(body.getByRole("button", { name: "Undo" })).toBeDisabled();
    await userEvent.click(body.getByRole("button", { name: "Add row below" }));
    await expect(body.getAllByRole("gridcell").length + body.getAllByRole("columnheader").length).toBe(6);
    await userEvent.click(body.getByRole("button", { name: "Undo" }));
    await expect(body.getAllByRole("gridcell").length + body.getAllByRole("columnheader").length).toBe(4);
    await userEvent.click(body.getByRole("button", { name: "Redo" }));
    await expect(body.getAllByRole("gridcell").length + body.getAllByRole("columnheader").length).toBe(6);
  },
};

export const CtrlZUndoesWhenFocusIsOnTheGrid: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Edit table" }));
    const body = within(dialog());
    await userEvent.click(body.getByRole("button", { name: "Add column right" }));
    body.getByRole("grid").focus();
    await userEvent.keyboard("{Control>}z{/Control}");
    await expect(body.getAllByRole("gridcell").length + body.getAllByRole("columnheader").length).toBe(4);
  },
};

export const ReadOnlyOffersViewingNotSaving: Story = {
  args: { disabled: true },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "View table" }));
    const body = within(dialog());
    await expect(body.queryByRole("button", { name: "Save" })).toBeNull();
    await expect(body.queryByRole("button", { name: "Merge cells" })).toBeNull();
    await expect(body.getByRole("button", { name: "Close" })).toBeVisible(); // the dialog's own
  },
};
