import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { requiredCaptions } from "../testing/requiredMarkers";
import type { TreeSelectNode } from "./TreeSelect";
import { TreeSelectField } from "./TreeSelectField";

const NODES: TreeSelectNode[] = [
  { id: "serial", label: "Serial bus", children: [{ id: "i2c", label: "I2C", children: [] }, { id: "spi", label: "SPI", children: [] }] },
  { id: "power", label: "Power", children: [] },
];

function Harness({ required }: { required?: boolean }) {
  const [value, setValue] = useState<string[]>([]);
  return (
    <TreeSelectField
      label="Connection type" help="The kind of interface." required={required} single searchable emptyLabel="Choose a type"
      nodes={NODES} value={value} onChange={setValue}
    />
  );
}

const meta: Meta<typeof Harness> = { title: "Components/TreeSelectField", component: Harness };
export default meta;

type Story = StoryObj<typeof Harness>;

export const CaptionHelpAndChoice: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Help: Connection type" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Connection type" }));
    await userEvent.click(within(document.body).getByRole("radio", { name: "I2C" }));
    await expect(canvas.getByRole("button", { name: "Connection type" })).toHaveTextContent("I2C");
  },
};

export const RequiredMarksTheCaption: Story = {
  args: { required: true },
  play: async ({ canvasElement }) => {
    await expect(requiredCaptions(canvasElement)).toEqual(["Connection type"]);
  },
};
