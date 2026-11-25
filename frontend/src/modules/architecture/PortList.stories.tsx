import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { expectContainerFits } from "../../testing/containerFits";
import { buildPort, CONNECTION_TYPES } from "./architectureFixtures";
import { PortList } from "./PortList";
import { openAddDialog } from "../../testing/storybook-helpers";

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
    const dialog = await openAddDialog(canvas, "Add port");
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Events");
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
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

/**
 * The list holds its row (name, direction, type, remove) at the widths of a narrow card and a wide page: below 34rem the
 * direction and type selects wrap under the name, above it they sit in their own column.
 *
 * @param width The column's width in CSS pixels.
 */
function fitsAt(width: number): Story {
  return {
    args: {
      // A connection type with a very long name makes its select wide: it must shrink to the column, not widen the row.
      connectionTypes: [
        ...CONNECTION_TYPES,
        { ...CONNECTION_TYPES[0], id: "ct-long", name: "Space-qualified redundant serial telemetry and command bus (version 2, flight model)", parent_ids: [] },
      ],
      ports: [
        buildPort({ id: "port-long", name: "Redundant telemetry uplink to the ground segment", connection_type_id: "ct-long" }),
        buildPort({ id: "port-2", name: "B", direction: "both", connection_type_id: "ct-long" }),
      ],
    },
    decorators: [(Story) => <div style={{ width }}><Story /></div>],
    play: async ({ canvasElement }) => {
      const canvas = within(canvasElement);
      await expect(canvas.getByLabelText("Direction of B")).toBeVisible();
      const select = canvas.getAllByLabelText(/^Connection type of /)[0];
      await expect(select.getBoundingClientRect().width).toBeLessThanOrEqual(width);
      await expectContainerFits(canvasElement.firstElementChild as HTMLElement, "ports list");
      const row = canvas.getByLabelText("Direction of B").getBoundingClientRect();
      const name = canvas.getAllByLabelText("Port name")[1].getBoundingClientRect();
      // Narrow: the selects are on the line below the name; wide: level with it.
      if (width < 544) await expect(row.top).toBeGreaterThanOrEqual(name.bottom - 1);
      else await expect(Math.abs(row.top - name.top)).toBeLessThan(name.height);
    },
  };
}

export const FitsAColumn280: Story = fitsAt(280);
export const FitsAColumn340: Story = fitsAt(340);
export const FitsAColumn390: Story = fitsAt(390);
export const FitsAColumn520: Story = fitsAt(520);
export const FitsAColumnJustOverTheWrapWidth560: Story = fitsAt(560);
export const FitsAWideColumn700: Story = fitsAt(700);
