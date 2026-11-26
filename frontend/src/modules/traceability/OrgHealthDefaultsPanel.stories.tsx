import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { OrgHealthDefaultsPanel } from "./OrgHealthDefaultsPanel";
import type { HealthDefault } from "./types";

const ORG_ID = "org-1";
const URL = `/api/v1/orgs/${ORG_ID}/modules/traceability/health-defaults`;
const OPTIONS = [1, 6, 12, 24, 48, 72, 120, 168, 240, 336];

const ON_DEMAND: HealthDefault = { mode: "on_demand", interval_hours: 24, interval_options: OPTIONS };

const meta: Meta<typeof OrgHealthDefaultsPanel> = {
  title: "Modules/Governance/OrgHealthDefaultsPanel",
  component: OrgHealthDefaultsPanel,
  args: { orgId: ORG_ID },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof OrgHealthDefaultsPanel>;

/** The saved mode is selected and the interval is offered only for the mode that uses it. */
export const ShowsTheDefault: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(ON_DEMAND);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("combobox", { name: "Default mode" })).toHaveValue("on_demand"));
    await expect(canvas.queryByRole("combobox", { name: "Default snapshot interval" })).toBeNull();
    await expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled();
  },
};

/** Choosing a snapshot at an interval reveals the interval; Save sends both values. */
export const SavesAnIntervalSnapshot: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(ON_DEMAND);
    spyOn(api, "put").mockResolvedValue({ mode: "snapshot_interval", interval_hours: 168, interval_options: OPTIONS });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Default mode" }), "snapshot_interval");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Default snapshot interval" }), "168");
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(URL, { mode: "snapshot_interval", interval_hours: 168 }));
    await expect(await within(document.body).findByText("The governance health default is saved.")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled();
  },
};

/** A mode that has no interval keeps the stored interval. */
export const KeepsTheIntervalForOtherModes: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ mode: "snapshot_interval", interval_hours: 72, interval_options: OPTIONS });
    spyOn(api, "put").mockResolvedValue({ mode: "snapshot_on_change", interval_hours: 72, interval_options: OPTIONS });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Default mode" }), "snapshot_on_change");
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(URL, { mode: "snapshot_on_change", interval_hours: 72 }));
  },
};

/** A refused save shows the server's message beside Save. */
export const SaveFailureShowsAnError: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(ON_DEMAND);
    spyOn(api, "put").mockRejectedValue(new Error("The interval is not offered."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Default mode" }), "snapshot_on_change");
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await expect(await canvas.findByText("The interval is not offered.")).toBeInTheDocument();
  },
};

/** A failed read offers Retry. */
export const LoadFailure: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new Error("down"));
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("The governance health default could not be loaded.")).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...ShowsTheDefault, globals: { theme: "dark" } };
