import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter } from "react-router-dom";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { ProjectContext } from "../../context/ProjectContextValue";
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
  // The list keeps its filters in the URL, so it needs a router.
  decorators: [(Story) => <MemoryRouter><Story /></MemoryRouter>],
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
    for (const header of ["Name", "Code", "Type", "Scope", "Size", "Status"]) await expect(table.getByRole("columnheader", { name: header })).toBeInTheDocument();
    await expect(table.getByText("Organisation")).toBeInTheDocument();
    await expect(table.getAllByText("Active").length).toBe(2);
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
