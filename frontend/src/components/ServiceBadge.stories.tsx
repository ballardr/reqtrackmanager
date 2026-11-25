import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { ServiceBadge } from "./ServiceBadge";

/** The one "Service" pill shown beside a service user's name wherever a user or principal is listed. */
const meta: Meta<typeof ServiceBadge> = { title: "Components/ServiceBadge", component: ServiceBadge };
export default meta;

type Story = StoryObj<typeof ServiceBadge>;

export const Default: Story = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Service")).toBeInTheDocument();
  },
};
