import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";

import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { SettingGroup } from "./SettingGroup";

/** One collapsible group of settings: closed by default, a pill and an accent edge for what is not at its default. */
const meta: Meta<typeof SettingGroup> = {
  title: "Components/SettingGroup", component: SettingGroup, decorators: [withStatefulAuth(buildUser())],
  args: { sectionKey: "story:group", title: "Borders", children: <input aria-label="Colour" /> },
};
export default meta;

type Story = StoryObj<typeof SettingGroup>;

export const ClosedByDefaultAndOpensOnClick: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("textbox", { name: "Colour" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Borders section" }));
    await expect(canvas.getByRole("textbox", { name: "Colour" })).toBeVisible();
  },
};

export const ChangedSettingsAreCountedOnTheClosedBar: Story = {
  args: { changed: 2 },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Borders section" })).toHaveAccessibleDescription("2 changed");
  },
};

export const AGivenSummaryReplacesTheCount: Story = {
  args: { changed: 1, summary: "A4 portrait" },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Borders section" })).toHaveAccessibleDescription("A4 portrait");
  },
};

export const AProblemHoldsTheGroupOpen: Story = {
  args: { problems: 1 },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("textbox", { name: "Colour" })).toBeVisible();
    await expect(canvas.getByRole("button", { name: "Borders section" })).toHaveAccessibleDescription("1 problem");
  },
};

export const DefaultOpenStartsOpen: Story = {
  args: { defaultOpen: true },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("textbox", { name: "Colour" })).toBeVisible();
  },
};
