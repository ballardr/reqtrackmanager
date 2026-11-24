import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter } from "react-router-dom";
import { expect, fn, screen, userEvent, waitFor, within } from "storybook/test";

import { ProjectContext } from "../../context/ProjectContextValue";
import { buildUser, withStatefulAuth } from "../../testing/storybook-helpers";
import { expectHeaderOrdersText, expectHeaderSorts } from "../../testing/sortHelpers";
import { expectStressStable, stressText } from "../../testing/stressFixtures";
import { TextStress } from "../../testing/TextStress";
import { RecordListView, type ListedRecord } from "./RecordListView";

interface Widget extends ListedRecord {
  kind: string | null;
  size: number;
}

const STATUS_LABEL = { draft: "Draft", active: "Active" };
const STATUS_TONE = { draft: "muted", active: "accent" } as const;
const SCOPE_LABEL = { organization: "Organisation", project: "Project" };

const WIDGETS: Widget[] = [
  { id: "w1", unique_code: "WGT-001", name: "Alpha", status: "active", scope: "project", kind: "Round", size: 3 },
  { id: "w2", unique_code: "WGT-002", organization_id: "org-1", name: "Beta", status: "draft", scope: "organization", kind: "Square", size: 5 },
  { id: "w3", unique_code: "WGT-003", name: "Gamma", status: "active", scope: "project", kind: null, size: 1 },
];

const meta: Meta<typeof RecordListView<Widget, string>> = {
  // The list keeps its filters in the URL, so it needs a router; the column choice is kept in the person's preferences.
  decorators: [withStatefulAuth(buildUser()), (Story) => <MemoryRouter><Story /></MemoryRouter>],
  title: "Modules/Stakeholders/RecordListView",
  component: RecordListView<Widget, string>,
  args: {
    records: WIDGETS, ariaLabel: "Widgets", sectionKey: "test.widgets", noun: "Widget", scopeLabel: "project",
    emptyText: "No widgets.", showScope: true, statusLabel: STATUS_LABEL, statusTone: STATUS_TONE, scopeLabels: SCOPE_LABEL,
    typeName: (w: Widget) => w.kind, searchText: (w: Widget) => w.name,
    columnsBeforeType: [], columnsAfterScope: [{ key: "size", label: "Size", render: (w: Widget) => String(w.size) }],
    includeArchived: false, onIncludeArchivedChange: fn(), onOpen: fn(), onCreate: fn(async () => undefined),
    renderCreateModal: ({ onSave, onCancel, error }) => (
      <div role="dialog" aria-label="Create widget">
        {error && <p>{error}</p>}
        <button onClick={() => onSave("values")}>Save widget</button>
        <button onClick={onCancel}>Cancel widget</button>
      </div>
    ),
  },
};
export default meta;

type Story = StoryObj<typeof RecordListView<Widget, string>>;

export const RendersFixedAndKindColumnsThroughLabelMaps: Story = {
  play: async ({ canvasElement }) => {
    const table = within(within(canvasElement).getByRole("table", { name: "Widgets" }));
    for (const header of ["Name", "Code", "Type", "Size", "Status"]) await expect(table.getByRole("columnheader", { name: header })).toBeInTheDocument();
    await expect(table.getAllByText("Active").length).toBe(2);
    // Scope is an optional column, off until chosen; its values render through the label map once it is.
    await expect(table.queryByRole("columnheader", { name: "Scope" })).not.toBeInTheDocument();
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Choose columns" }));
    await userEvent.click(await screen.findByRole("checkbox", { name: "Scope" }));
    await expect(table.getByRole("columnheader", { name: "Scope" })).toBeInTheDocument();
    await expect(table.getByText("Organisation")).toBeInTheDocument();
    await expect(table.queryByText("organization")).not.toBeInTheDocument();
  },
};

/** A record the organisation owns shows its code qualified by the organisation's code; a project record by the project's. */
export const CodesAreQualifiedByOwner: Story = {
  decorators: [(Story) => (
    <ProjectContext.Provider
      value={{ terminology: {}, projectCode: "PRJ", organizationId: "org-1", organizationCode: "ACME" }}
    >
      <Story />
    </ProjectContext.Provider>
  )],
  play: async ({ canvasElement }) => {
    const table = within(within(canvasElement).getByRole("table", { name: "Widgets" }));
    await expect(table.getByText("PRJ-WGT-001")).toBeInTheDocument();
    await expect(table.getByText("ACME-WGT-002")).toBeInTheDocument();
  },
};

/** A kind with no lifecycle (an Engagement) leaves out the Status and archived controls, and can rename the type column. */
export const NoStatusNoArchiveAndACustomTypeLabel: Story = {
  args: {
    statusLabel: undefined, statusTone: undefined, onIncludeArchivedChange: undefined, typeLabel: "Channel", newLabel: "Log widget",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = within(canvas.getByRole("table", { name: "Widgets" }));
    await expect(table.getByRole("columnheader", { name: "Channel" })).toBeInTheDocument();
    await expect(table.queryByRole("columnheader", { name: "Type" })).not.toBeInTheDocument();
    await expect(table.queryByRole("columnheader", { name: "Status" })).not.toBeInTheDocument();
    await expect(canvas.queryByText("Show archived")).not.toBeInTheDocument();
    await expect(canvas.queryByText("All statuses")).not.toBeInTheDocument();
    await expect(canvas.getByText("All channels")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Log widget" })).toBeInTheDocument();
  },
};

export const ScopeColumnCanBeHidden: Story = {
  args: { showScope: false },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("columnheader", { name: "Scope" })).not.toBeInTheDocument();
  },
};

export const StatusAndTypeBadgesFilter: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Draft" }));
    await waitFor(() => expect(canvas.queryByText("Alpha")).not.toBeInTheDocument());
    await expect(canvas.getByText("Beta")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Draft" })); // toggles the filter off
    await userEvent.click(canvas.getByRole("button", { name: "Round" }));
    await waitFor(() => expect(canvas.queryByText("Beta")).not.toBeInTheDocument());
    await expect(canvas.getByText("Alpha")).toBeInTheDocument();
  },
};

export const SearchFiltersByTheCallersText: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText("Search Widgets"), "gam");
    await waitFor(() => expect(canvas.queryByText("Alpha")).not.toBeInTheDocument());
    await expect(canvas.getByText("Gamma")).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  args: { records: [] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("No widgets.")).toBeInTheDocument();
  },
};

export const RowClickOpensTheRecord: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByText("Alpha"));
    await expect(args.onOpen).toHaveBeenCalledWith(WIDGETS[0]);
  },
};

export const CreateRunsTheCallerAndClosesOnSuccess: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "New Widget" }));
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Save widget" }));
    await waitFor(() => expect(args.onCreate).toHaveBeenCalledWith("values", [], []));
    await waitFor(() => expect(within(canvasElement).queryByRole("dialog")).not.toBeInTheDocument());
  },
};

export const CreateFailureKeepsTheModalOpenWithTheMessage: Story = {
  args: { onCreate: fn(async () => { throw new Error("Nope."); }) },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "New Widget" }));
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Save widget" }));
    await waitFor(() => expect(within(canvasElement).getByText("Nope.")).toBeInTheDocument());
    await expect(within(canvasElement).getByRole("dialog")).toBeInTheDocument();
  },
};

export const ToolbarRendersBesideTheNewButton: Story = {
  args: { toolbar: <button className="btn">Extra action</button> },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Extra action" })).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...RendersFixedAndKindColumnsThroughLabelMaps, globals: { theme: "dark" } };

/** The fixed columns and a kind's own column (given a `sortValue`) sort on a header click; a record with no type sorts last. */
export const HeadersSortTheRecords: Story = {
  args: {
    columnsAfterScope: [{ key: "size", label: "Size", sortable: true, sortValue: (w: Widget) => w.size, render: (w: Widget) => String(w.size) }],
  },
  play: async ({ canvasElement }) => {
    const table = within(canvasElement).getByRole("table", { name: "Widgets" });
    await expectHeaderOrdersText(table, "Name");
    await expectHeaderSorts(table, "Size", ["1", "3", "5"]);
    await expectHeaderSorts(table, "Type", ["Round", "Square", "—"]);
  },
};

/** Opens the column chooser and returns its dialog. */
async function openChooser(canvasElement: HTMLElement) {
  await userEvent.click(within(canvasElement).getByRole("button", { name: "Choose columns" }));
  return screen.findByRole("dialog", { name: "Columns" });
}

/**
 * Name, Code and Status are always drawn (ticked and locked in the chooser); every other column is optional, and Scope
 * is the one that starts off. Choosing a column shows it, and the reset restores the defaults.
 */
export const ColumnChooserShowsOptionalColumns: Story = {
  play: async ({ canvasElement }) => {
    const table = within(within(canvasElement).getByRole("table", { name: "Widgets" }));
    await expect(table.queryByRole("columnheader", { name: "Scope" })).not.toBeInTheDocument();
    const dialog = await openChooser(canvasElement);
    for (const locked of ["Name", "Code", "Status"]) {
      const box = within(dialog).getByRole("checkbox", { name: locked });
      await expect(box).toBeChecked();
      await expect(box).toBeDisabled();
    }
    await expect(within(dialog).getByRole("checkbox", { name: "Type" })).toBeChecked();
    await expect(within(dialog).getByRole("checkbox", { name: "Scope" })).not.toBeChecked();
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Scope" }));
    await expect(table.getByRole("columnheader", { name: "Scope" })).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Type" }));
    await expect(table.queryByRole("columnheader", { name: "Type" })).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Show the default columns" }));
    await expect(table.queryByRole("columnheader", { name: "Scope" })).not.toBeInTheDocument();
    await expect(table.getByRole("columnheader", { name: "Type" })).toBeInTheDocument();
  },
};

/** A hidden column is still offered by Sort by and an export, and a list sorted by it keeps that sort. */
export const HiddenColumnStillSorts: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("columnheader", { name: "Scope" })).not.toBeInTheDocument();
    const sortBy = canvas.getByRole("combobox", { name: "Sort by" });
    await expect(within(sortBy).getByRole("option", { name: "Scope" })).toBeInTheDocument();
    await userEvent.selectOptions(sortBy, "Scope");
    // Organisation sorts before Project; the Scope column stays hidden.
    await waitFor(() => expect(within(canvas.getByRole("table", { name: "Widgets" })).getAllByRole("row")[1]).toHaveTextContent("Beta"));
    await expect(canvas.queryByRole("columnheader", { name: "Scope" })).not.toBeInTheDocument();
  },
};

/** A list with a single optional column that is on by default offers no chooser (nothing to choose). */
export const NoChooserWithNothingToChoose: Story = {
  args: { showScope: false, typeName: undefined, columnsAfterScope: [] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button", { name: "Choose columns" })).not.toBeInTheDocument();
  },
};

const LONG_WIDGETS = (long: boolean): Widget[] =>
  [1, 2, 3].map((n) => ({
    id: `w${n}`, unique_code: stressText(long, `WGT-00${n}`, "code"), name: stressText(long, `Widget ${n}`, n === 2 ? "word" : "name"),
    status: n === 2 ? "draft" : "active", scope: "project", kind: stressText(long, "Round", "word"), size: n,
  }));

/** The list at one width, with short text and then long names, an unbroken word and a long code in several rows. */
const longTextAt = (width: number): Story => ({
  render: (args) => <TextStress width={width} render={(long) => <RecordListView<Widget, string> {...args} records={LONG_WIDGETS(long)} />} />,
  play: async ({ canvasElement }) => {
    await expectStressStable(canvasElement);
  },
});

/** Long text at a wide width: the table keeps its shape. */
export const LongText: Story = longTextAt(960);
/** Long text at about half a screen. */
export const LongTextHalfScreen: Story = longTextAt(640);
/** Long text at a narrow width. */
export const LongTextNarrow: Story = longTextAt(420);

/** The Name column holds its floor width (12rem) at every width, however much the other columns want. */
export const NameKeepsItsFloor: Story = {
  render: (args) => (
    <div style={{ width: 420 }}>
      <RecordListView<Widget, string> {...args} records={LONG_WIDGETS(true)} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const header = within(canvasElement).getByRole("columnheader", { name: "Name" });
    await expect(header.getBoundingClientRect().width).toBeGreaterThanOrEqual(12 * 16 - 1);
    await expect(header).toHaveClass("directory-table-floor");
    // The kind's own columns drop while the list has under 40rem of room; Name, Code, Type and Status never do.
    await expect(within(canvasElement).queryAllByRole("columnheader", { name: "Size" })).toHaveLength(0);
    await expect(within(canvasElement).getByRole("columnheader", { name: "Status" })).toBeVisible();
    await expect(within(canvasElement).getByRole("columnheader", { name: "Type" })).toBeVisible();
  },
};
