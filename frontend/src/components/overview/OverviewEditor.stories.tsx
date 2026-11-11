import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import type { OverviewCatalogue, OverviewLayout, OverviewMetricSpec, OverviewWidget } from "../../api/types";
import { projectScopeApi } from "../../api/projectScope";
import { withRouter, withTerminology } from "../../testing/storybook-helpers";
import { OverviewEditor } from "./OverviewEditor";

const widget = (id: string, type: string, config: Record<string, unknown>, extra: Partial<OverviewWidget> = {}): OverviewWidget => ({
  id, type, title: null, width: 3, height: 2, scope: null, visible: true, config, ...extra,
});

const catalogue: OverviewCatalogue = {
  widget_types: [
    { key: "metric_tile", label: "Metric tile", description: "", module_key: null, width: 3, height: 2 },
    { key: "gauge", label: "Gauge", description: "", module_key: null, width: 3, height: 4 },
    { key: "text", label: "Text", description: "", module_key: null, width: 6, height: 3 },
    { key: "compliance:standards_status", label: "Compliance standards", description: "", module_key: "compliance", width: 12, height: 2 },
  ],
  metrics: [
    { key: "requirement_count", label: "Requirements", unit: "count", scalar: true, breakdown: false, params: [], module_key: null },
    { key: "file_count", label: "Files", unit: "count", scalar: true, breakdown: false, params: [], module_key: null },
    { key: "record_count", label: "Record count", unit: "count", scalar: true, breakdown: false, params: ["filters", "record_type"], module_key: null },
  ],
  record_types: [{ type: "risk", label: "Risks", filter_params: ["status"] }],
  max_widgets: 3,
};

const layout = (source: OverviewLayout["source"], widgets: OverviewWidget[], scope: OverviewLayout["scope"] = "this"): OverviewLayout => ({
  scope, widgets, source, inherited_source: source === "own" ? "default" : null, can_customise: true,
});

const two = [widget("a", "metric_tile", { metric: "file_count" }), widget("b", "metric_tile", { metric: "requirement_count" }, { title: "Total requirements" })];

function mockServer(current: OverviewLayout, relatives = { has_parents: true, has_children: true, truncated: false }) {
  spyOn(projectScopeApi, "options").mockResolvedValue(relatives);
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/overview-layout")) return current;
    if (path.endsWith("/overview-catalogue")) return catalogue;
    return [];
  });
  spyOn(api, "post").mockImplementation(async (_path: string, body?: unknown) => ({
    results: Object.fromEntries((body as { metrics: OverviewMetricSpec[] }).metrics.map((spec) => [
      spec.id, { state: "ok", unit: "count", label: spec.metric, projects: 1, value: 4, breakdown: null },
    ])),
  }));
  return spyOn(api, "put").mockImplementation(async (_path: string, body?: unknown) => ({ ...current, ...(body as object) }));
}

const meta: Meta<typeof OverviewEditor> = {
  title: "Components/Overview/OverviewEditor",
  component: OverviewEditor,
  decorators: [withTerminology(), withRouter("/projects/project-1", "*")],
  args: { target: { kind: "project", projectId: "project-1" }, onSaved: fn(), onCancel: fn() },
};
export default meta;

type Story = StoryObj<typeof OverviewEditor>;

/** The draft is the layout in force, drawn with live figures; the bar says how many of the limit are used. */
export const ShowsTheLayoutWithLiveFigures: Story = {
  beforeEach: () => { mockServer(layout("organisation", two)); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("2 of 3 widgets")).toBeInTheDocument();
    await expect((await canvas.findAllByText("4")).length).toBe(2);
    await expect(canvas.getByText("Total requirements")).toBeInTheDocument();
    // No own layout yet, so there is nothing to restore, and no badge says where the layout comes from.
    await expect(canvas.queryByRole("button", { name: "Restore default" })).not.toBeInTheDocument();
    await expect(canvas.queryByText(/Built-in layout|Organisation default/)).not.toBeInTheDocument();
  },
};

export const RestoreIsOfferedOnlyOnceTheLayoutIsOwn: Story = {
  beforeEach: () => {
    mockServer(layout("own", two));
    spyOn(api, "delete").mockResolvedValue({});
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Restore default" }));
    const dialog = await within(document.body).findByRole("dialog", { name: "Restore the default overview?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Restore default" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/api/v1/projects/project-1/overview-layout"));
    await waitFor(() => expect(args.onSaved).toHaveBeenCalled());
  },
};

export const HideThenSaveSendsTheDraft: Story = {
  beforeEach: () => { mockServer(layout("own", two, "children")); },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Hide Files" }));
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalled());
    const body = (api.put as unknown as { mock: { calls: [string, { scope: string; widgets: OverviewWidget[] }][] } }).mock.calls[0][1];
    await expect(body.scope).toBe("children");
    await expect(body.widgets.map((w) => [w.id, w.visible])).toEqual([["a", false], ["b", true]]);
    await waitFor(() => expect(args.onSaved).toHaveBeenCalled());
  },
};

/** The overview's scope is a setting of the overview, offered only for the scopes this project's relatives allow. */
export const ScopeIsASettingOfTheOverview: Story = {
  beforeEach: () => { mockServer(layout("own", two), { has_parents: true, has_children: false, truncated: false }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = await canvas.findByRole("combobox", { name: "Show records from" });
    await expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["This project", "This + parent projects"]);
    await userEvent.selectOptions(select, "parents");
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalled());
    await expect((api.put as unknown as { mock: { calls: [string, { scope: string }][] } }).mock.calls[0][1].scope).toBe("parents");
  },
};

export const NoScopeChoiceWithoutRelatives: Story = {
  beforeEach: () => { mockServer(layout("own", two), { has_parents: false, has_children: false, truncated: false }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText("2 of 3 widgets");
    await expect(canvas.queryByRole("combobox", { name: "Show records from" })).not.toBeInTheDocument();
  },
};

export const AddingAWidgetOpensItsSettings: Story = {
  beforeEach: () => { mockServer(layout("default", [])); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("No widgets. Add one to build the overview.")).toBeInTheDocument();
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Add widget" }), "gauge");
    const panel = await within(document.body).findByRole("dialog", { name: /^Settings:/ });
    await expect(within(panel).getByRole("combobox", { name: /Metric/ })).toHaveValue("requirement_count");
    await expect(within(panel).getByRole("spinbutton", { name: /Maximum/ })).toHaveValue(100);
    await userEvent.click(within(panel).getByRole("button", { name: "Done" }));
    await expect(await canvas.findByText("1 of 3 widgets")).toBeInTheDocument();
  },
};

/** Size and scope are set in the widget's settings as well as by dragging; the draft changes at once. */
export const SettingsChangeTheSizeScopeAndText: Story = {
  beforeEach: () => { mockServer(layout("own", [widget("n", "text", { markdown: "Old note" }, { title: "Notes" })])); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Settings for Notes" }));
    const panel = await within(document.body).findByRole("dialog", { name: "Settings: Notes" });
    const width = within(panel).getByRole("spinbutton", { name: /Width/ });
    await userEvent.clear(width);
    await userEvent.type(width, "9");
    const text = within(panel).getByRole("textbox", { name: "Text" });
    await userEvent.clear(text);
    await userEvent.type(text, "New **note**");
    // A text widget always reads this project, so it offers no scope.
    await expect(within(panel).queryByRole("combobox", { name: "Show records from" })).not.toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: "Done" }));
    const cell = canvasElement.querySelector('[data-widget-id="n"]') as HTMLElement;
    await expect(cell.style.getPropertyValue("--w")).toBe("9");
    await expect(within(cell).getByText("note").tagName).toBe("STRONG");
  },
};

/** A module's widget is offered by name and starts at the size its module declared, then is an ordinary widget. */
export const AModuleWidgetIsOfferedAndStartsAtItsOwnSize: Story = {
  beforeEach: () => { mockServer(layout("default", [])); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Add widget" }), "compliance:standards_status");
    const panel = await within(document.body).findByRole("dialog", { name: "Settings: Compliance standards" });
    await expect(within(panel).getByRole("spinbutton", { name: /Width/ })).toHaveValue(12);
    await expect(within(panel).getByRole("spinbutton", { name: /Height/ })).toHaveValue(2);
    await userEvent.click(within(panel).getByRole("button", { name: "Done" }));
    // The tools name it by its module's label, and it can be moved, hidden and removed like any widget.
    await expect(await canvas.findByRole("button", { name: "Move Compliance standards" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Remove Compliance standards" })).toBeInTheDocument();
  },
};

export const AFigureWidgetCanOverrideTheOverviewScope: Story = {
  beforeEach: () => { mockServer(layout("own", two)); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Settings for Files" }));
    const panel = await within(document.body).findByRole("dialog", { name: "Settings: Files" });
    const select = within(panel).getByRole("combobox", { name: "Show records from" });
    await expect(select).toHaveValue("");
    await userEvent.selectOptions(select, "children");
    await userEvent.click(within(panel).getByRole("button", { name: "Done" }));
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalled());
    const body = (api.put as unknown as { mock: { calls: [string, { widgets: OverviewWidget[] }][] } }).mock.calls[0][1];
    await expect(body.widgets[0].scope).toBe("children");
  },
};

export const CancelAsksBeforeDiscardingChanges: Story = {
  beforeEach: () => { mockServer(layout("own", two)); },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Remove Files" }));
    await userEvent.click(canvas.getByRole("button", { name: "Cancel" }));
    const dialog = await within(document.body).findByRole("dialog", { name: "Discard your changes?" });
    await expect(args.onCancel).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Discard changes" }));
    await waitFor(() => expect(args.onCancel).toHaveBeenCalled());
  },
};

export const SaveFailureIsShown: Story = {
  beforeEach: () => {
    mockServer(layout("own", two));
    spyOn(api, "put").mockRejectedValue(new Error("An overview may hold at most 24 widgets."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Save" }));
    await expect(await canvas.findByText("An overview may hold at most 24 widgets.")).toBeInTheDocument();
  },
};

/** An organisation's default is edited the same way, with labelled blocks in place of figures and all four scopes on offer. */
export const OrganisationDefaultUsesBlocks: Story = {
  args: { target: { kind: "organisation", organizationId: "org-1" } },
  beforeEach: () => { mockServer(layout("own", two)); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText("2 of 3 widgets");
    await expect(canvasElement.querySelectorAll("[data-placeholder]")).toHaveLength(2);
    const select = canvas.getByRole("combobox", { name: "Show records from" });
    await expect(within(select).getAllByRole("option")).toHaveLength(4);
    await expect(api.post).not.toHaveBeenCalled();
  },
};

export const LightTheme: Story = { ...ShowsTheLayoutWithLiveFigures, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ShowsTheLayoutWithLiveFigures, globals: { theme: "dark" } };

/** A dashboard page of an organisation reads and writes its own endpoints, offers no project scope, and saves the layout. */
export const DashboardTargetUsesTheDashboardEndpoints: Story = {
  args: { target: { kind: "dashboard", organizationId: "org-1", dashboardId: "page-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === "/api/v1/orgs/org-1/dashboards/page-1") {
        return { dashboard: { id: "page-1", name: "Board", is_default: false, restricted: false, viewers: [], can_manage: true }, scope: "this", widgets: two, built_in: false };
      }
      if (path === "/api/v1/orgs/org-1/dashboard-catalogue") return catalogue;
      throw new Error(`unmocked GET: ${path}`);
    });
    spyOn(api, "post").mockImplementation(async (_path: string, body?: unknown) => ({
      results: Object.fromEntries((body as { metrics: OverviewMetricSpec[] }).metrics.map((spec) => [
        spec.id, { state: "ok", unit: "count", label: spec.metric, projects: 1, value: 4, breakdown: null },
      ])),
    }));
    spyOn(api, "put").mockResolvedValue({});
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("2 of 3 widgets")).toBeInTheDocument();
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/v1/orgs/org-1/dashboards/page-1/metrics", expect.anything()));
    // A page has no project scope to choose and no default to return to.
    await expect(canvas.queryByRole("combobox", { name: "Project scope" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Restore default" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/v1/orgs/org-1/dashboards/page-1/layout", expect.objectContaining({ scope: "this" })));
    await expect(args.onSaved).toHaveBeenCalled();
  },
};
