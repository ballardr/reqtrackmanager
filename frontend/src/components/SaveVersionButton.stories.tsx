import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, userEvent, waitFor, within } from "storybook/test";

import { saveVersion } from "../testing/saveVersionHelpers";
import { SaveVersionButton } from "./SaveVersionButton";

/** The "Save new version" button of a versioned editor: it opens a popover for an optional note, then saves. */
const meta: Meta<typeof SaveVersionButton> = {
  title: "Components/SaveVersionButton",
  component: SaveVersionButton,
  args: { disabled: false, saving: false, onSave: fn(async () => true) },
};
export default meta;

type Story = StoryObj<typeof SaveVersionButton>;

/** No note field is on the page until the button is pressed. */
export const AsksForANoteOnlyWhenPressed: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("textbox", { name: "Note on this change" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Save new version" }));
    await expect(within(await screen.findByRole("dialog", { name: "Save new version" })).getByRole("textbox", { name: "Note on this change" })).toBeInTheDocument();
  },
};

export const SavesWithTheNote: Story = {
  play: async ({ canvasElement, args }) => {
    await saveVersion(within(canvasElement).getByRole("button", { name: "Save new version" }), "Added the summary");
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith("Added the summary"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  },
};

/** The note is optional, and Enter in the field saves. */
export const SavesWithoutANoteAndOnEnter: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Save new version" }));
    const field = within(await screen.findByRole("dialog", { name: "Save new version" })).getByRole("textbox", { name: "Note on this change" });
    await userEvent.type(field, "{Enter}");
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(""));
  },
};

/** A refused save (a version conflict, say) keeps the popover and the note. */
export const ARefusedSaveKeepsThePopoverOpen: Story = {
  args: { onSave: fn(async () => false) },
  play: async ({ canvasElement, args }) => {
    await saveVersion(within(canvasElement).getByRole("button", { name: "Save new version" }), "Kept");
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith("Kept"));
    const popover = within(await screen.findByRole("dialog", { name: "Save new version" }));
    await expect(popover.getByRole("textbox", { name: "Note on this change" })).toHaveValue("Kept");
  },
};

export const CancelClosesWithoutSaving: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Save new version" }));
    await userEvent.click(within(await screen.findByRole("dialog", { name: "Save new version" })).getByRole("button", { name: "Cancel" }));
    await expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await expect(args.onSave).not.toHaveBeenCalled();
  },
};

export const DisabledWhenThereIsNothingToSave: Story = {
  args: { disabled: true },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Save new version" })).toBeDisabled();
  },
};

export const LightTheme: Story = { ...AsksForANoteOnlyWhenPressed, globals: { theme: "light" } };
export const DarkTheme: Story = { ...AsksForANoteOnlyWhenPressed, globals: { theme: "dark" } };
