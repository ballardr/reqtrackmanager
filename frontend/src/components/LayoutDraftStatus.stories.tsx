import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { LayoutDraftStatus } from "./LayoutDraftStatus";

/** The draft controls beside Save new version: one sentence about the draft, the Autosave switch and, with autosave off, Save draft and Discard changes. */
const meta: Meta<typeof LayoutDraftStatus> = {
  title: "Components/LayoutDraftStatus",
  component: LayoutDraftStatus,
  args: {
    autosave: true, onAutosave: fn(), savedAt: null, pending: false, saving: false, failure: null, unreadable: null,
    onSaveDraft: fn(), onDiscardChanges: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof LayoutDraftStatus>;

const status = (canvasElement: HTMLElement) => within(canvasElement).getByRole("status", { name: "Draft status" });

export const NoDraftYet: Story = {
  play: async ({ canvasElement }) => {
    await expect(status(canvasElement)).toHaveTextContent("No draft");
    await expect(within(canvasElement).queryByRole("button", { name: "Save draft" })).not.toBeInTheDocument();
  },
};

export const SavedAtATime: Story = {
  args: { savedAt: "2026-11-03T09:15:00Z" },
  play: async ({ canvasElement }) => {
    await expect(status(canvasElement)).toHaveTextContent(/^Draft saved \d/);
  },
};

export const Saving: Story = {
  args: { saving: true, pending: true },
  play: async ({ canvasElement }) => {
    await expect(status(canvasElement)).toHaveTextContent("Saving…");
  },
};

/** The reason is worded by the designer: the line that does not read, offline, or a refusal. */
export const NotSavedAndWhy: Story = {
  args: { unreadable: "line 7", pending: true },
  play: async ({ canvasElement }) => {
    await expect(status(canvasElement)).toHaveTextContent("Not saved: line 7");
  },
};

export const OfflineOutranksEverythingElse: Story = {
  args: { failure: "offline", pending: true, unreadable: "line 7" },
  play: async ({ canvasElement }) => {
    await expect(status(canvasElement)).toHaveTextContent("Not saved: offline");
  },
};

export const ServerRefusal: Story = {
  args: { failure: "error", pending: true },
  play: async ({ canvasElement }) => {
    await expect(status(canvasElement)).toHaveTextContent("Not saved: the server refused it");
  },
};

/** With autosave off the person is told the work is not in a draft and gets the two actions that matter. */
export const AutosaveOffOffersSaveDraftAndDiscardChanges: Story = {
  args: { autosave: false, pending: true },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(status(canvasElement)).toHaveTextContent("Changes not saved to a draft");
    await userEvent.click(canvas.getByRole("button", { name: "Save draft" }));
    await expect(args.onSaveDraft).toHaveBeenCalled();
    await userEvent.click(canvas.getByRole("button", { name: "Discard changes" }));
    await expect(args.onDiscardChanges).toHaveBeenCalled();
  },
};

export const AutosaveOffWithNothingPendingDisablesBoth: Story = {
  args: { autosave: false, pending: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Save draft" })).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "Discard changes" })).toBeDisabled();
  },
};

/** Text that does not read cannot be saved however the person asks. */
export const SaveDraftIsDisabledWhileTheContentDoesNotRead: Story = {
  args: { autosave: false, pending: true, unreadable: "line 3" },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Save draft" })).toBeDisabled();
  },
};

export const TheSwitchChangesTheSetting: Story = {
  play: async ({ canvasElement, args }) => {
    const toggle = within(canvasElement).getByRole("switch", { name: "Autosave drafts" });
    await expect(toggle).toBeChecked();
    await userEvent.click(toggle);
    await expect(args.onAutosave).toHaveBeenCalledWith(false);
  },
};
