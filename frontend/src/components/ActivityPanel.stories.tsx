import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { buildChangeEntry } from "../testing/storybook-helpers";
import { ActivityPanel } from "./ActivityPanel";

const meta: Meta<typeof ActivityPanel> = {
  title: "Components/ActivityPanel",
  component: ActivityPanel,
};
export default meta;

type Story = StoryObj<typeof ActivityPanel>;

export const Entries: Story = {
  args: {
    entries: [
      buildChangeEntry({ action: "updated", actor_display_name: "Alex Morgan" }),
      buildChangeEntry({
        entity_type: "change_request",
        entity_id: "cr-1",
        action: "submitted",
        actor_display_name: "Jamie Lee",
        detail: { change_note: "Clarified the reset link expiry window" },
      }),
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Alex Morgan updated")).toBeInTheDocument();
    await expect(
      canvas.getByText("Jamie Lee submitted — Clarified the reset link expiry window")
    ).toBeInTheDocument();
    await expect(canvas.getByText("Requirement")).toBeInTheDocument();
    await expect(canvas.getByText("Change request")).toBeInTheDocument();
  },
};

export const NoActivity: Story = {
  args: { entries: [] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("No activity yet.")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...Entries, globals: { theme: "light" } };
export const DarkTheme: Story = { ...Entries, globals: { theme: "dark" } };
