import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { RecordListView, type ListedRecord } from "./RecordListView";

interface Widget extends ListedRecord {
  kind: string | null;
  size: number;
}

const STATUS_LABEL = { draft: "Draft", active: "Active" };
const STATUS_TONE = { draft: "muted", active: "accent" } as const;
const SCOPE_LABEL = { organization: "Organisation", project: "Project" };

const WIDGETS: Widget[] = [
  { id: "w1", name: "Alpha", status: "active", scope: "project", kind: "Round", size: 3 },
  { id: "w2", name: "Beta", status: "draft", scope: "organization", kind: "Square", size: 5 },
  { id: "w3", name: "Gamma", status: "active", scope: "project", kind: null, size: 1 },
];

const meta: Meta<typeof RecordListView<Widget, string>> = {
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
    for (const header of ["Name", "Type", "Scope", "Size", "Status"]) await expect(table.getByRole("columnheader", { name: header })).toBeInTheDocument();
    await expect(table.getByText("Organisation")).toBeInTheDocument();
    await expect(table.getAllByText("Active").length).toBe(2);
    await expect(table.queryByText("organization")).not.toBeInTheDocument();
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
    await waitFor(() => expect(args.onCreate).toHaveBeenCalledWith("values"));
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
