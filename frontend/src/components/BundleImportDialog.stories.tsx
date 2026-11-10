import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { ApiError } from "../api/client";

import { BundleImportDialog } from "./BundleImportDialog";
import { TextField } from "./FormFields";

const meta: Meta<typeof BundleImportDialog> = {
  title: "Components/BundleImportDialog",
  component: BundleImportDialog,
  args: {
    title: "Import project",
    fileLabel: "Project bundle (.zip)",
    fileHelp: "A .zip file produced by the project export.",
    onClose: fn(),
    onImport: fn(async () => {}),
    children: <TextField helpNotNeeded label="Name" value="" onChange={() => {}} />,
  },
};
export default meta;

type Story = StoryObj<typeof BundleImportDialog>;

const zip = () => new File(["zip"], "bundle.zip", { type: "application/zip" });

/** Import stays unavailable until a file is chosen, and the file is required. */
export const NeedsAFile: Story = {
  play: async ({ canvasElement }) => {
    const dialog = within(within(canvasElement.ownerDocument.body).getByRole("dialog", { name: "Import project" }));
    await expect(dialog.getByRole("button", { name: "Import" })).toBeDisabled();
    await expect(dialog.getByText("Project bundle (.zip)")).toBeInTheDocument();
    await expect(dialog.getByRole("button", { name: "Help: Project bundle (.zip)" })).toBeInTheDocument();
  },
};

/** The caller's own condition (a missing name) also holds Import back, and a chosen file runs the import. */
export const ImportsTheChosenFile: Story = {
  args: { canImport: true },
  play: async ({ canvasElement, args }) => {
    const dialog = within(within(canvasElement.ownerDocument.body).getByRole("dialog", { name: "Import project" }));
    await userEvent.upload(dialog.getByLabelText("Project bundle (.zip)") as HTMLInputElement, zip());
    await userEvent.click(dialog.getByRole("button", { name: "Import" }));
    await waitFor(() => expect(args.onImport).toHaveBeenCalledWith(expect.any(File), false));
  },
};

export const BlockedByTheCaller: Story = {
  args: { canImport: false },
  play: async ({ canvasElement }) => {
    const dialog = within(within(canvasElement.ownerDocument.body).getByRole("dialog", { name: "Import project" }));
    await userEvent.upload(dialog.getByLabelText("Project bundle (.zip)") as HTMLInputElement, zip());
    await expect(dialog.getByRole("button", { name: "Import" })).toBeDisabled();
  },
};

/** A failed import keeps the dialog open and shows the message. */
export const ShowsAFailure: Story = {
  args: { onImport: fn(async () => { throw new Error("The file is not a project export."); }) },
  play: async ({ canvasElement }) => {
    const dialog = within(within(canvasElement.ownerDocument.body).getByRole("dialog", { name: "Import project" }));
    await userEvent.upload(dialog.getByLabelText("Project bundle (.zip)") as HTMLInputElement, zip());
    await userEvent.click(dialog.getByRole("button", { name: "Import" }));
    await expect(await dialog.findByText("The file is not a project export.")).toBeInTheDocument();
  },
};

const FILES_REFUSAL = () => new ApiError(403, "File uploads are disabled on this deployment.", {
  code: "uploads_disabled", file_count: 3, file_bytes: 2048,
});

/** The server refused because the bundle carries files and uploads are disabled: the dialog offers Cancel import or
 * Import without files, and the second repeats the import with `skipFiles`. */
export const OffersImportWithoutFiles: Story = {
  args: {
    onImport: fn(async (_file: File, skipFiles: boolean) => { if (!skipFiles) throw FILES_REFUSAL(); }),
  },
  play: async ({ canvasElement, args }) => {
    const dialog = within(within(canvasElement.ownerDocument.body).getByRole("dialog", { name: "Import project" }));
    await userEvent.upload(dialog.getByLabelText("Project bundle (.zip)") as HTMLInputElement, zip());
    await userEvent.click(dialog.getByRole("button", { name: "Import" }));
    await expect(await dialog.findByText("3 files (2.0 KB) cannot be stored because file uploads are disabled on this deployment.")).toBeInTheDocument();
    await expect(dialog.getByRole("button", { name: "Cancel import" })).toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: "Import without files" }));
    await waitFor(() => expect(args.onImport).toHaveBeenLastCalledWith(expect.any(File), true));
  },
};

/** Cancel import closes the dialog without a second request. */
export const CancelImportClosesTheDialog: Story = {
  args: { onImport: fn(async () => { throw FILES_REFUSAL(); }) },
  play: async ({ canvasElement, args }) => {
    const dialog = within(within(canvasElement.ownerDocument.body).getByRole("dialog", { name: "Import project" }));
    await userEvent.upload(dialog.getByLabelText("Project bundle (.zip)") as HTMLInputElement, zip());
    await userEvent.click(dialog.getByRole("button", { name: "Import" }));
    await userEvent.click(await dialog.findByRole("button", { name: "Cancel import" }));
    await expect(args.onClose).toHaveBeenCalled();
    await expect(args.onImport).toHaveBeenCalledTimes(1);
  },
};
