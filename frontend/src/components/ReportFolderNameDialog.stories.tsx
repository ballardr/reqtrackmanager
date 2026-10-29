import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, userEvent, waitFor, within } from "storybook/test";

import { requiredCaptions } from "../testing/requiredMarkers";
import { ReportFolderNameDialog } from "./ReportFolderNameDialog";

/** The small form that names a new folder or renames one in the Report setup list. */
const meta: Meta<typeof ReportFolderNameDialog> = {
  title: "Components/Reports/ReportFolderNameDialog",
  component: ReportFolderNameDialog,
  args: { mode: "add", parent: "", onSubmit: fn(async () => undefined), onClose: fn() },
};
export default meta;

type Story = StoryObj<typeof ReportFolderNameDialog>;

export const NamingANewFolderNeedsAName: Story = {
  play: async ({ args }) => {
    const dialog = within(await screen.findByRole("dialog", { name: "New folder" }));
    await expect(requiredCaptions(document.body)).toEqual(["Name of the new folder"]);
    await expect(dialog.getByRole("button", { name: "Add" })).toBeDisabled();
    await userEvent.type(dialog.getByRole("textbox"), "Audit{Enter}");
    await waitFor(() => expect(args.onSubmit).toHaveBeenCalledWith("Audit"));
    await waitFor(() => expect(args.onClose).toHaveBeenCalled());
  },
};

export const ANewFolderInsideAnotherNamesTheParent: Story = {
  args: { parent: "Handover" },
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "New folder inside" }));
    await expect(dialog.getByRole("textbox", { name: /Name of the new folder inside Handover/ })).toBeInTheDocument();
  },
};

export const RenamingStartsFromTheCurrentName: Story = {
  args: { mode: "rename", parent: "Handover", initialName: "Handover" },
  play: async ({ args }) => {
    const dialog = within(await screen.findByRole("dialog", { name: "Rename" }));
    await expect(dialog.getByRole("textbox", { name: /New name for Handover/ })).toHaveValue("Handover");
    await userEvent.click(dialog.getByRole("button", { name: "Save name" }));
    await waitFor(() => expect(args.onSubmit).toHaveBeenCalledWith("Handover"));
  },
};

export const AServerRefusalIsShownAndTheFormStaysOpen: Story = {
  args: { onSubmit: fn(async () => { throw new Error("A folder with that name already exists here."); }), onClose: fn() },
  play: async ({ args }) => {
    const dialog = within(await screen.findByRole("dialog", { name: "New folder" }));
    await userEvent.type(dialog.getByRole("textbox"), "Audit");
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
    await expect(await dialog.findByText("A folder with that name already exists here.")).toBeInTheDocument();
    await expect(args.onClose).not.toHaveBeenCalled();
  },
};
