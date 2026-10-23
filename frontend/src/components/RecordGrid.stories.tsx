import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { MemoryRouter } from "react-router-dom";

import { ApiError } from "../api/client";
import { buildGrid, failing, fakeRecordTables } from "../testing/recordTablesFixtures";
import { RecordGrid } from "./RecordGrid";

const meta: Meta<typeof RecordGrid> = {
  title: "Components/RecordGrid",
  component: RecordGrid,
  decorators: [(Story) => <MemoryRouter><Story /></MemoryRouter>],
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
    for (const heading of ["Code", "Title", "Priority", "Severity", "Frequency", "Confidence", "Intentional", "Date identified"]) {
      await expect(canvas.getByRole("columnheader", { name: heading })).toBeInTheDocument();
    }
    await expect(canvas.queryByRole("columnheader", { name: "Status" })).not.toBeInTheDocument();
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

/** Reloading with unsaved changes asks first; confirming drops them. */
export const ReloadAsksBeforeDiscardingChanges: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Reload" }));
    await waitFor(() => expect(args.tables!.grid).toHaveBeenCalledTimes(2));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Priority for PNP-001" }), "High");
    await userEvent.click(canvas.getByRole("button", { name: "Reload" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.click(dialog.getByRole("button", { name: "Discard and reload" }));
    await waitFor(() => expect(args.tables!.grid).toHaveBeenCalledTimes(3));
    await expect(await canvas.findByRole("combobox", { name: "Priority for PNP-001" })).toHaveValue("Medium");
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
