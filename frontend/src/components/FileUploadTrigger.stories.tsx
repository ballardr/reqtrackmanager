import type { Meta, StoryObj } from "@storybook/react-vite";
import { Paperclip } from "lucide-react";
import { expect, fn, userEvent, within } from "storybook/test";

import { FileUploadTrigger } from "./FileUploadTrigger";

const meta: Meta<typeof FileUploadTrigger> = {
  title: "Components/FileUploadTrigger",
  component: FileUploadTrigger,
  args: { onSelect: fn() },
};
export default meta;

type Story = StoryObj<typeof FileUploadTrigger>;

export const IconAndText: Story = {
  args: { children: <><Paperclip size={14} /> Attach a file</> },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Attach a file")).toBeInTheDocument();
  },
};

/** Selecting a file fires `onSelect` with the chosen `File` and resets the
 * underlying input's value, so choosing the same filename again still
 * fires a change event (see `CommentThread`'s repeated-attachment case). */
export const SelectingAFileCallsOnSelect: Story = {
  args: { children: <><Paperclip size={14} /> Attach a file</> },
  play: async ({ canvasElement, args }) => {
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });
    const input = canvasElement.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, file);
    await expect(args.onSelect).toHaveBeenCalledWith(file);
    await expect(input.value).toBe("");
  },
};

export const Disabled: Story = {
  args: { children: <><Paperclip size={14} /> Attach a file</>, disabled: true },
  play: async ({ canvasElement }) => {
    const input = canvasElement.querySelector('input[type="file"]') as HTMLInputElement;
    await expect(input).toBeDisabled();
  },
};

/** `showTrigger={false}` mounts only the (still hidden) input — used by
 * `CsvImportWizard` when a split-button elsewhere opens the file picker
 * itself via a forwarded ref, rather than rendering its own visible
 * trigger a second time on the same screen. */
export const HiddenTriggerStillMountsInput: Story = {
  args: { children: <><Paperclip size={14} /> Attach a file</>, showTrigger: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByText("Attach a file")).not.toBeInTheDocument();
    await expect(canvasElement.querySelector('input[type="file"]')).not.toBeNull();
  },
};

export const LightTheme: Story = { ...IconAndText, globals: { theme: "light" } };
export const DarkTheme: Story = { ...IconAndText, globals: { theme: "dark" } };
