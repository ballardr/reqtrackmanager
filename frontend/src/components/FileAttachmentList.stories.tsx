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
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("requirements-source.pdf")).toBeInTheDocument();
    await expect(canvas.getByText("screenshot.png")).toBeInTheDocument();
    const file = new File(["data"], "spec.pdf", { type: "application/pdf" });
    const input = canvasElement.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, file);
    await expect(args.onUpload).toHaveBeenCalledWith(file);
  },
};

/** Only a picture's row has the details button. */
export const OnlyAPictureHasDetails: Story = {
  args: { files, onUpload: fn(), onRemove: fn() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Details of screenshot.png" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Details of requirements-source.pdf" })).toBeNull();
  },
};

export const RemoveFile: Story = {
  args: { files, onUpload: fn(), onRemove: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Remove requirements-source.pdf" }));
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
    await expect(canvas.queryByRole("button", { name: /Remove|Attach/ })).not.toBeInTheDocument();
  },
};

export const NoCallbacksReadOnly: Story = {
  args: { files },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button", { name: /Remove|Attach/ })).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...WithFilesAndUpload, globals: { theme: "light" } };
export const DarkTheme: Story = { ...WithFilesAndUpload, globals: { theme: "dark" } };

/** A picture can be marked confidential (kept out of reports): the list says what it affects and the row shows a badge. */
export const APictureCanBeMarkedConfidential: Story = {
  args: {
    files: [buildFileAsset({ id: "f3", filename: "site.png", content_type: "image/png" }), files[0]],
    onUpload: fn(),
    setConfidential: fn(async (id: string, confidential: boolean) => buildFileAsset({ id, filename: "site.png", content_type: "image/png", confidential })),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/left out of reports/)).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Mark requirements-source.pdf confidential" })).toBeNull();
    await userEvent.click(canvas.getByRole("button", { name: "Mark site.png confidential" }));
    await expect(args.setConfidential).toHaveBeenCalledWith("f3", true);
    await expect(await canvas.findByText("Confidential")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Clear the confidential mark on site.png" }));
    await expect(args.setConfidential).toHaveBeenLastCalledWith("f3", false);
  },
};

/** A file already marked confidential shows the badge and offers to clear the mark. */
export const AConfidentialPictureShowsItsBadge: Story = {
  args: { files: [buildFileAsset({ id: "f3", filename: "site.png", content_type: "image/png", confidential: true })], onUpload: fn() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Confidential")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Clear the confidential mark on site.png" })).toHaveAttribute("aria-pressed", "true");
  },
};

/** A refused change (not the uploader or a manager) leaves the row as it was. */
export const ARefusedChangeLeavesTheMarkAlone: Story = {
  args: {
    files: [buildFileAsset({ id: "f4", filename: "site.png", content_type: "image/png" })],
    setConfidential: fn(async () => { throw new Error("Only the uploader or a project manager can change this."); }),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Mark site.png confidential" }));
    await expect(args.setConfidential).toHaveBeenCalled();
    await expect(canvas.queryByText("Confidential")).toBeNull();
  },
};
