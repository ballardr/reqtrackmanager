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
    await waitFor(() => expect(args.onImport).toHaveBeenCalledWith(expect.any(File), false, { mapping: {}, keep_original_email: false }));
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
    await waitFor(() => expect(args.onImport).toHaveBeenLastCalledWith(expect.any(File), true, expect.anything()));
  },
};

/** The files do not fit under the organisation's storage limit: the dialog gives the size and the space left, with the
 * same two choices. */
export const OffersImportWithoutFilesWhenTheyDoNotFit: Story = {
  args: {
    onImport: fn(async (_file: File, skipFiles: boolean) => {
      if (!skipFiles) {
        throw new ApiError(403, "The storage limit of this organisation has been reached.", {
          code: "storage_quota_exceeded", file_count: 2, file_bytes: 3 * 1024 * 1024, remaining_bytes: 1024 * 1024,
        });
      }
    }),
  },
  play: async ({ canvasElement, args }) => {
    const dialog = within(within(canvasElement.ownerDocument.body).getByRole("dialog", { name: "Import project" }));
    await userEvent.upload(dialog.getByLabelText("Project bundle (.zip)") as HTMLInputElement, zip());
    await userEvent.click(dialog.getByRole("button", { name: "Import" }));
    await expect(await dialog.findByText("2 files (3.0 MB) do not fit in the storage space left for this organisation (1.0 MB).")).toBeInTheDocument();
    await expect(dialog.getByRole("button", { name: "Cancel import" })).toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: "Import without files" }));
    await waitFor(() => expect(args.onImport).toHaveBeenLastCalledWith(expect.any(File), true, expect.anything()));
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

const PEOPLE = [
  { email: "alex@old.example", display_name: "Alex Morgan", resolution: "stand_in" as const, member_id: null, member_name: null },
  { email: "sam@new.example", display_name: "Sam Lee", resolution: "member" as const, member_id: "u-sam", member_name: "Sam Lee" },
];

/** With the People step on, choosing a file reads the people; a reassignment and the keep-email switch go to the import. */
export const ReadsThePeopleAndPassesTheChoices: Story = {
  args: {
    people: { load: fn(async () => PEOPLE), members: [{ user_id: "u-sam", display_name: "Sam Lee" }], dependsOn: "org-1" },
  },
  play: async ({ canvasElement, args }) => {
    const dialog = within(within(canvasElement.ownerDocument.body).getByRole("dialog", { name: "Import project" }));
    await userEvent.upload(dialog.getByLabelText("Project bundle (.zip)") as HTMLInputElement, zip());
    const select = await dialog.findByRole("combobox", { name: "Import Alex Morgan as" });
    await userEvent.selectOptions(select, "u-sam");
    await userEvent.click(dialog.getByRole("checkbox", { name: "Keep original email addresses in the history" }));
    await userEvent.click(dialog.getByRole("button", { name: "Import" }));
    await waitFor(() => expect(args.onImport).toHaveBeenCalledWith(
      expect.any(File), false, { mapping: { "alex@old.example": "u-sam" }, keep_original_email: true },
    ));
  },
};

/** A bundle that cannot be read shows the message in place of the table. */
export const ShowsAPeopleFailure: Story = {
  args: { people: { load: fn(async () => { throw new Error("Not a valid export bundle."); }), members: [], dependsOn: "org-1" } },
  play: async ({ canvasElement }) => {
    const dialog = within(within(canvasElement.ownerDocument.body).getByRole("dialog", { name: "Import project" }));
    await userEvent.upload(dialog.getByLabelText("Project bundle (.zip)") as HTMLInputElement, zip());
    await expect(await dialog.findByRole("alert")).toHaveTextContent("Not a valid export bundle.");
  },
};
