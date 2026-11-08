import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

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
    await waitFor(() => expect(args.onImport).toHaveBeenCalledWith(expect.any(File)));
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
