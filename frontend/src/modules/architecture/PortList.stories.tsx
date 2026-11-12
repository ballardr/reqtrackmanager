import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildPort, CONNECTION_TYPES } from "./architectureFixtures";
import { PortList } from "./PortList";

const meta: Meta<typeof PortList> = {
  title: "Modules/Architecture/PortList",
  component: PortList,
  args: {
    ports: [buildPort(), buildPort({ id: "port-2", name: "Telemetry", direction: "out", connection_type_id: null, connection_type_name: null })],
    connectionTypes: CONNECTION_TYPES, onAdd: fn().mockResolvedValue(undefined), onChange: fn().mockResolvedValue(undefined),
    onRemove: fn().mockResolvedValue(undefined),
  },
};
export default meta;

type Story = StoryObj<typeof PortList>;

export const ShowsDirectionAndTypeThroughLabels: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("Direction of HTTPS API")).toHaveDisplayValue("In");
    await expect(canvas.getByLabelText("Direction of Telemetry")).toHaveDisplayValue("Out");
    await expect(canvas.getByLabelText("Connection type of HTTPS API")).toHaveDisplayValue("REST API");
  },
};

export const ChangesAreReportedOneFieldAtATime: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByLabelText("Direction of Telemetry"), "both");
    await expect(args.onChange).toHaveBeenCalledWith("port-2", { direction: "both" });
    await userEvent.selectOptions(canvas.getByLabelText("Connection type of Telemetry"), "ct-2");
    await expect(args.onChange).toHaveBeenCalledWith("port-2", { connection_type_id: "ct-2" });
    await userEvent.type(canvas.getByLabelText("Port name", { selector: "input[placeholder='Port name']" }), "Events");
    await userEvent.click(canvas.getByRole("button", { name: "Add port" }));
    await expect(args.onAdd).toHaveBeenCalledWith({ name: "Events", direction: "both", connection_type_id: null });
  },
};

/** A shared element's ports are listed without controls. */
export const ReadOnlyListsThePorts: Story = {
  args: { readOnly: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/HTTPS API · In/)).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Add port" })).not.toBeInTheDocument();
  },
};
