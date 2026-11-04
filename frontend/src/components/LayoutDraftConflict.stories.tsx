import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { LayoutDraftConflict } from "./LayoutDraftConflict";

/** Shown when someone else changed the shared draft while this editor was writing to it; autosave stays paused until a choice is made. */
const meta: Meta<typeof LayoutDraftConflict> = {
  title: "Components/LayoutDraftConflict",
  component: LayoutDraftConflict,
  args: {
    draft: { base_version: 2, revision: 5, updated_by: "user-2", updated_by_name: "Sam Rivera", updated_at: "2026-11-03T09:15:00Z" },
    onLoadTheirs: fn(), onKeepMine: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof LayoutDraftConflict>;

export const NamesWhoChangedTheDraftAndOffersBothWays: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("alert", { name: "Someone else changed this draft" })).toHaveTextContent("Sam Rivera changed the draft at");
    await userEvent.click(canvas.getByRole("button", { name: "Load their changes" }));
    await expect(args.onLoadTheirs).toHaveBeenCalled();
    await userEvent.click(canvas.getByRole("button", { name: "Keep mine" }));
    await expect(args.onKeepMine).toHaveBeenCalled();
  },
};

/** The other editor published or discarded the draft, so there is nobody to name. */
export const TheDraftMayBeGone: Story = {
  args: { draft: null },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("alert")).toHaveTextContent("The draft was published or discarded by someone else.");
  },
};
