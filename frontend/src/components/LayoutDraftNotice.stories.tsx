import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { LayoutDraftNotice } from "./LayoutDraftNotice";

/** The line saying a layout has unpublished work: who, when and from which version, with the two actions. */
const meta: Meta<typeof LayoutDraftNotice> = {
  title: "Components/LayoutDraftNotice",
  component: LayoutDraftNotice,
  args: {
    summary: { base_version: 2, revision: 3, updated_by: "user-2", updated_by_name: "Sam Rivera", updated_at: "2026-11-03T09:15:00Z" },
    currentVersion: 2, onDiscard: fn(), onShowSaved: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof LayoutDraftNotice>;

export const NamesTheAuthorAndTheBaseVersion: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("note", { name: "Draft" })).toHaveTextContent(/^Draft from Sam Rivera, .*, based on version 2\./);
    await userEvent.click(canvas.getByRole("button", { name: "Show saved version" }));
    await expect(args.onShowSaved).toHaveBeenCalled();
    await userEvent.click(canvas.getByRole("button", { name: "Discard draft" }));
    await expect(args.onDiscard).toHaveBeenCalled();
  },
};

export const SaysWhenVersionsWerePublishedSinceTheDraftBegan: Story = {
  args: { currentVersion: 4 },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("note", { name: "Draft" })).toHaveTextContent("Version 4 was saved since this draft began.");
  },
};

export const AnUnknownAuthorIsSomeone: Story = {
  args: { summary: { base_version: 2, revision: 3, updated_by: null, updated_by_name: null, updated_at: "2026-11-03T09:15:00Z" } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("note", { name: "Draft" })).toHaveTextContent("Draft from someone");
  },
};

export const WithoutActionsItIsJustText: Story = {
  args: { onDiscard: undefined, onShowSaved: undefined },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button")).not.toBeInTheDocument();
  },
};
