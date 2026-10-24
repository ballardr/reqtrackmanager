import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";

import { ApiError } from "../api/client";
import { buildGrid, failing, fakeRecordTables } from "../testing/recordTablesFixtures";
import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { RecordGrid } from "./RecordGrid";

const meta: Meta<typeof RecordGrid> = {
  title: "Components/RecordGrid",
  component: RecordGrid,
  decorators: [(Story) => <MemoryRouter><Story /></MemoryRouter>, withStatefulAuth(buildUser({ ui_preferences: {} }))],
  args: {
    projectId: "project-1",
    recordType: "pain_point",
    filters: "priority=high",
    contextKeys: ["title"],
    onSaved: fn(),
    tables: fakeRecordTables(),
  },
};
export default meta;

type Story = StoryObj<typeof RecordGrid>;

/** The grid loads the list with the page's filters and shows the editable columns beside the code and title. */
export const LoadsTheListWithThePagesFilters: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Pain points grid" });
    await expect(args.tables!.grid).toHaveBeenCalledWith("project-1", "pain_point", "priority=high");
    for (const heading of ["Code", "Title", "Priority", "Severity", "Frequency", "Confidence", "Intentional", "Date identified", "Status", "Editing"]) {
      await expect(canvas.getByRole("columnheader", { name: heading })).toBeInTheDocument();
    }
    await expect(canvas.getByText("Slow reports")).toBeInTheDocument();
    await expect(canvas.getByRole("combobox", { name: "Severity for PNP-002" })).toHaveValue("Major");
    await expect(canvas.getByText("4 records")).toBeInTheDocument();
  },
};

/** A changed cell is marked, counted on the Save button, and Discard puts the saved values back. */
export const ChangedCellsAreCountedAndCanBeDiscarded: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const severity = await canvas.findByRole("combobox", { name: "Severity for PNP-001" });
    await expect(canvas.getByRole("button", { name: "Save changes" })).toBeDisabled();
    await userEvent.selectOptions(severity, "Blocker");
    await expect(severity.closest("td")).toHaveClass("record-grid__cell--changed");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Priority for PNP-002" }), "Low");
    await expect(canvas.getByRole("button", { name: "Save 2 changes" })).toBeEnabled();
    await userEvent.selectOptions(severity, "");
    await expect(canvas.getByRole("button", { name: "Save 1 change" })).toBeEnabled();
    await userEvent.click(canvas.getByRole("button", { name: "Discard changes" }));
    await expect(canvas.getByRole("combobox", { name: "Priority for PNP-002" })).toHaveValue("High");
    await expect(canvas.getByRole("button", { name: "Save changes" })).toBeDisabled();
  },
};

/** Save sends one request per changed row, with the changed cells and what they held when loaded. */
export const SaveSendsOneRequestPerChangedRow: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Severity for PNP-001" }), "Blocker");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Frequency for PNP-001" }), "Rare");
    await userEvent.click(canvas.getByRole("checkbox", { name: "Intentional for PNP-002" }));
    await userEvent.click(canvas.getByRole("button", { name: "Save 2 changes" }));
    await waitFor(() => expect(args.tables!.saveRow).toHaveBeenCalledTimes(2));
    await expect(args.tables!.saveRow).toHaveBeenCalledWith(
      "project-1", "pain_point", "PNP-001", { severity: "Blocker", frequency: "Rare" }, { severity: "", frequency: "" },
    );
    await expect(args.tables!.saveRow).toHaveBeenCalledWith(
      "project-1", "pain_point", "PNP-002", { is_intentional: "false" }, { is_intentional: "true" },
    );
    await expect(await within(document.body).findByText("2 saved.")).toBeInTheDocument();
    await expect(args.onSaved).toHaveBeenCalled();
    await expect(canvas.getByRole("button", { name: "Save changes" })).toBeDisabled();
    await expect(canvas.getByRole("combobox", { name: "Severity for PNP-001" })).toHaveValue("Blocker");
  },
};

/** A row that fails stays changed with its message under it; the others still save, and the toast counts both. */
export const AFailedRowStaysChangedWithItsMessage: Story = {
  args: {
    tables: fakeRecordTables({
      saveRow: fn(async (_p: string, _t: string, code: string, cells: Record<string, string>) => {
        if (code === "PNP-002") throw new ApiError(409, "Severity was changed by someone else (now 'Minor'); reload before editing it again.");
        return { ...buildGrid().rows[0], cells: { ...buildGrid().rows[0].cells, ...cells } };
      }),
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Severity for PNP-001" }), "Blocker");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Severity for PNP-002" }), "Cosmetic");
    await userEvent.click(canvas.getByRole("button", { name: "Save 2 changes" }));
    await expect(await canvas.findByRole("alert")).toHaveTextContent("PNP-002: Severity was changed by someone else");
    await expect(await within(document.body).findByText("1 saved, 1 failed.")).toBeInTheDocument();
    await expect(canvas.getByRole("combobox", { name: "Severity for PNP-002" }).closest("td")).toHaveClass("record-grid__cell--changed");
    await expect(canvas.getByRole("button", { name: "Save 1 change" })).toBeEnabled();
  },
};

/** A score cell of a Pain Point scored per persona, and every cell of a closed one, are text with the reason. */
export const LockedCellsAndRowsShowTheirReason: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table");
    await expect(canvas.queryByRole("combobox", { name: "Severity for PNP-003" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("combobox", { name: "Priority for PNP-003" })).toBeEnabled();
    await expect(canvas.getAllByText(/scored per persona/i).length).toBeGreaterThan(0);
    await expect(canvas.queryByRole("combobox", { name: "Priority for PNP-004" })).not.toBeInTheDocument();
    await expect(canvas.getAllByText(/terminal outcome/i).length).toBeGreaterThan(0);
  },
};

/** Enter moves to the same column in the next row; Shift+Enter goes back. */
export const EnterMovesDownTheColumn: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const first = await canvas.findByRole("combobox", { name: "Priority for PNP-001" });
    first.focus();
    await userEvent.keyboard("{Enter}");
    await expect(canvas.getByRole("combobox", { name: "Priority for PNP-002" })).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await expect(canvas.getByRole("combobox", { name: "Priority for PNP-003" })).toHaveFocus();
    await userEvent.keyboard("{Shift>}{Enter}{/Shift}");
    await expect(canvas.getByRole("combobox", { name: "Priority for PNP-002" })).toHaveFocus();
  },
};

/** Arrow keys move down and up a date column; a number or date cell is a shared input. */
export const ArrowKeysMoveThroughADateColumn: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const first = await canvas.findByLabelText("Date identified for PNP-001");
    first.focus();
    await userEvent.keyboard("{ArrowDown}");
    await expect(canvas.getByLabelText("Date identified for PNP-002")).toHaveFocus();
    await userEvent.keyboard("{ArrowUp}");
    await expect(first).toHaveFocus();
  },
};

/** A person who may not update sees the values as text and no Save button. */
export const WithoutEditRightsTheGridIsReadOnly: Story = {
  args: { tables: fakeRecordTables({ grid: fn(async () => buildGrid({ can_edit: false })) }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table");
    await expect(canvas.queryByRole("button", { name: /Save/ })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("combobox", { name: "Priority for PNP-001" })).not.toBeInTheDocument();
    await expect(canvas.getByText(/view these records but not change them/)).toBeInTheDocument();
  },
};

/** A list longer than the row cap says so and asks for narrower filters. */
export const ALongListSaysItWasCut: Story = {
  args: { tables: fakeRecordTables({ grid: fn(async () => buildGrid({ total: 812, truncated: true })) }) },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText(/Showing the first 4 of 812 records/)).toBeInTheDocument();
  },
};

/** A load failure is shown instead of an empty grid. */
export const ALoadFailureIsShown: Story = {
  args: { tables: fakeRecordTables({ grid: failing("The grid is unavailable.") }) },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("alert")).toHaveTextContent("The grid is unavailable.");
  },
};

/** No match for the filters is said plainly. */
export const NoRowsSaysSo: Story = {
  args: { tables: fakeRecordTables({ grid: fn(async () => buildGrid({ rows: [], total: 0 })) }) },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("No records match these filters.")).toBeInTheDocument();
  },
};

/** A row's code links to the record's page when the page says where it is. */
export const TheCodeLinksToTheRecord: Story = {
  args: { recordHref: (row) => `/projects/${row.project_id}/pain-points/${row.id}` },
  play: async ({ canvasElement }) => {
    const link = await within(canvasElement).findByRole("link", { name: "PNP-001" });
    await expect(link).toHaveAttribute("href", "/projects/project-1/pain-points/r1");
  },
};

/** Each row says whether it can be edited, with the reason in the Editing column, beside its status. */
export const EveryRowStatesWhetherItCanBeEdited: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table");
    const editing = async (code: string) => within(canvas.getByText(code).closest("tr")!);
    const closed = await editing("PNP-004");
    await expect(closed.getByText("Closed")).toBeInTheDocument();
    await expect(closed.getByText("Read-only")).toBeInTheDocument();
    await expect(closed.getAllByText(/terminal outcome/).length).toBeGreaterThan(0);
    const perPersona = await editing("PNP-003");
    await expect(perPersona.getByText("Partly editable")).toBeInTheDocument();
    await expect(perPersona.getAllByText(/scored per persona/).length).toBeGreaterThan(0);
    const open = await editing("PNP-001");
    await expect(open.getByText("Submitted")).toBeInTheDocument();
    await expect(open.getByText("Editable")).toBeInTheDocument();
  },
};

/** The Columns control hides shown columns (editable ones too) and the grid drops them. */
export const ColumnsCanBeChosen: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Columns" }));
    const picker = within(await within(document.body).findByRole("dialog"));
    await userEvent.click(picker.getByRole("checkbox", { name: "Show Severity" }));
    await userEvent.click(picker.getByRole("checkbox", { name: "Show Editing" }));
    await userEvent.click(picker.getByRole("checkbox", { name: "Show Status" }));
    await expect(canvas.queryByRole("columnheader", { name: "Severity" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("columnheader", { name: "Editing" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("combobox", { name: "Severity for PNP-001" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("columnheader", { name: "Priority" })).toBeInTheDocument();
  },
};

/** A column with unsaved changes cannot be hidden, so a change is never saved out of sight. */
export const AColumnWithChangesStaysShown: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Severity for PNP-001" }), "Blocker");
    await userEvent.click(canvas.getByRole("button", { name: "Columns" }));
    const picker = within(await within(document.body).findByRole("dialog"));
    await expect(picker.getByRole("checkbox", { name: "Show Severity" })).toBeDisabled();
    await expect(picker.getByRole("checkbox", { name: "Show Frequency" })).toBeEnabled();
  },
};

/** A locked value starts at the same left edge as the select text above and below it, so the column lines up. */
export const LockedValuesAlignWithTheControlsOfTheirColumn: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = await canvas.findByRole("combobox", { name: "Severity for PNP-002" });
    const locked = canvas.getByText("Minor", { selector: ".record-grid__locked" });
    const textLeft = (element: Element) => {
      const box = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return box.left + parseFloat(style.borderLeftWidth) + parseFloat(style.paddingLeft);
    };
    await expect(Math.abs(textLeft(locked) - textLeft(select))).toBeLessThanOrEqual(1);
  },
};

/** With a `toolbarHost` the controls render there, in the order Columns, Discard, Save, a divider, so a page can put them on its view toggle's row. */
export const ToolbarRendersInThePagesRow: Story = {
  render: (args) => {
    const Host = () => {
      const [host, setHost] = useState<HTMLElement | null>(null);
      return (
        <>
          <div className="row" style={{ alignItems: "center" }}>
            <div ref={setHost} data-testid="host" className="row" style={{ alignItems: "center" }} />
            <button className="btn">List</button>
          </div>
          <RecordGrid {...args} toolbarHost={host} />
        </>
      );
    };
    return <Host />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table");
    const host = within(canvas.getByTestId("host"));
    const left = (name: string | RegExp) => host.getByRole("button", { name }).getBoundingClientRect().left;
    await expect(left("Columns")).toBeLessThan(left("Discard changes"));
    await expect(left("Discard changes")).toBeLessThan(left("Save changes"));
    await expect(host.getByRole("separator")).toBeInTheDocument();
    await expect(canvas.getByTestId("host").nextElementSibling!.getBoundingClientRect().left).toBeGreaterThan(host.getByRole("separator").getBoundingClientRect().right);
    // Not duplicated in the grid itself.
    await expect(canvas.getAllByRole("button", { name: "Columns" })).toHaveLength(1);
  },
};
