import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import type { FileAsset } from "../api/types";
import { buildFileAsset } from "../testing/storybook-helpers";
import { FileAttachmentList } from "./FileAttachmentList";

const files: FileAsset[] = [
  buildFileAsset({ id: "f1", filename: "requirements-source.pdf" }),
  buildFileAsset({ id: "f2", filename: "screenshot.png", content_type: "image/png" }),
];

const meta: Meta<typeof FileAttachmentList> = {
  title: "Components/FileAttachmentList",
  component: FileAttachmentList,
};
export default meta;

type Story = StoryObj<typeof FileAttachmentList>;

export const WithFilesAndUpload: Story = {
  args: { files, onUpload: fn(), onRemove: fn() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("requirements-source.pdf")).toBeInTheDocument();
    await expect(canvas.getByText("screenshot.png")).toBeInTheDocument();
  },
};

export const RemoveFile: Story = {
  args: { files, onUpload: fn(), onRemove: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const row = canvas.getByText("requirements-source.pdf").closest<HTMLElement>(".row")!;
    await userEvent.click(within(row).getByRole("button"));
    await expect(args.onRemove).toHaveBeenCalledWith("f1");
  },
};

export const Empty: Story = {
  args: { files: [], onUpload: fn() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByText(/\.pdf|\.png/)).not.toBeInTheDocument();
  },
};

/** `disabled` with an `emptyHint` (the requirement-locked case) shows the
 * explanatory text instead of an upload control — never just silently
 * removes it. */
export const DisabledShowsHintInsteadOfUpload: Story = {
  args: {
    files,
    disabled: true,
    emptyHint: "This requirement is approved — new attachments must be added via a change request.",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/new attachments must be added via a change request/)).toBeInTheDocument();
    await expect(canvas.queryByRole("button")).not.toBeInTheDocument();
  },
};

export const NoCallbacksReadOnly: Story = {
  args: { files },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button")).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...WithFilesAndUpload, globals: { theme: "light" } };
export const DarkTheme: Story = { ...WithFilesAndUpload, globals: { theme: "dark" } };
