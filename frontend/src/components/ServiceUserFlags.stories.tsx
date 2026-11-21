import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { ServiceUserFlags } from "./ServiceUserFlags";

/** The access-review flags of a service user, each a pill with a tooltip saying what it means. */
const meta: Meta<typeof ServiceUserFlags> = { title: "Components/ServiceUserFlags", component: ServiceUserFlags };
export default meta;

type Story = StoryObj<typeof ServiceUserFlags>;

export const BothFlags: Story = {
  args: { flags: ["no_responsible", "administrator"] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("No responsible party")).toBeInTheDocument();
    await expect(canvas.getByText("Administrator rights")).toBeInTheDocument();
  },
};

export const NoFlagsDrawsNothing: Story = {
  args: { flags: [] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByText("No responsible party")).not.toBeInTheDocument();
  },
};
