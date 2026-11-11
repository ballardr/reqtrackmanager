import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import type { OverviewCatalogue, OverviewLayout, OverviewWidget } from "../../api/types";
import { withRouter, withTerminology } from "../../testing/storybook-helpers";
import { OrgOverviewDefaultPanel } from "./OrgOverviewDefaultPanel";

const widget = (id: string, metric: string): OverviewWidget => ({
  id, type: "metric_tile", title: null, width: 3, height: 2, scope: null, visible: true, config: { metric },
});

const catalogue: OverviewCatalogue = {
  widget_types: [{ key: "metric_tile", label: "Metric tile", description: "", module_key: null, width: 3, height: 2 }],
  metrics: [
    { key: "requirement_count", label: "Requirements", unit: "count", scalar: true, breakdown: false, params: [], module_key: null },
    { key: "file_count", label: "Files", unit: "count", scalar: true, breakdown: false, params: [], module_key: null },
  ],
  record_types: [],
  max_widgets: 6,
};

const layout = (source: OverviewLayout["source"], widgets: OverviewWidget[]): OverviewLayout => ({
  scope: "this", widgets, source, inherited_source: null, can_customise: true,
});

function mockServer(current: OverviewLayout) {
  spyOn(api, "get").mockImplementation(async (path: string) => (path.endsWith("/overview-catalogue") ? catalogue : current));
  return spyOn(api, "put").mockImplementation(async (_path: string, body?: unknown) => ({ ...current, ...(body as object) }));
}

const meta: Meta<typeof OrgOverviewDefaultPanel> = {
  title: "Components/Overview/OrgOverviewDefaultPanel",
  component: OrgOverviewDefaultPanel,
  decorators: [withTerminology(), withRouter("/orgs/org-1/admin", "*")],
  args: { organizationId: "org-1" },
};
export default meta;

type Story = StoryObj<typeof OrgOverviewDefaultPanel>;

/** No default of its own: the row says the built-in layout applies and the editor is closed. */
export const BuiltIn: Story = {
  beforeEach: () => { mockServer(layout("default", [])); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Built-in layout")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Edit overview default" })).toBeInTheDocument();
    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
  },
};

export const Customised: Story = {
  beforeEach: () => { mockServer(layout("own", [widget("a", "file_count"), widget("b", "requirement_count")])); },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("Customised: 2 widgets")).toBeInTheDocument();
  },
};

/** The editor opens in a dialog; saving closes it and the row reads the stored layout again. */
export const EditOpensTheEditorInADialog: Story = {
  beforeEach: () => { mockServer(layout("own", [widget("a", "file_count"), widget("b", "requirement_count")])); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Edit overview default" }));
    const dialog = await within(document.body).findByRole("dialog", { name: "Default overview" });
    await userEvent.click(await within(dialog).findByRole("button", { name: "Hide Files" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalled());
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
  },
};

/** Closing with unsaved changes asks first; keeping the edits leaves the dialog open. */
export const DismissingWithChangesAsksFirst: Story = {
  beforeEach: () => { mockServer(layout("own", [widget("a", "file_count")])); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Edit overview default" }));
    const dialog = await within(document.body).findByRole("dialog", { name: "Default overview" });
    await userEvent.click(await within(dialog).findByRole("button", { name: "Hide Files" }));
    await userEvent.keyboard("{Escape}");
    await expect(await within(document.body).findByRole("dialog", { name: /Discard/ })).toBeInTheDocument();
    await expect(api.put).not.toHaveBeenCalled();
  },
};
