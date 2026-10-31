import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, userEvent, waitFor, within } from "storybook/test";

import { buildFolderApi, openFolderPopover } from "../testing/reportFolderFixtures";
import { buildPackApi, buildPackSummary } from "../testing/reportPackFixtures";
import { requiredCaptions } from "../testing/requiredMarkers";
import { withToast } from "../testing/storybook-helpers";
import { ReportPackFormModal } from "./ReportPackFormModal";

/** Create and edit dialog of a report pack: a name, a description and a folder. */
const meta: Meta<typeof ReportPackFormModal> = {
  title: "Components/Reports/ReportPackFormModal",
  component: ReportPackFormModal,
  decorators: [withToast()],
  args: { onClose: fn(), onSaved: fn(), folderApi: buildFolderApi() },
};
export default meta;

type Story = StoryObj<typeof ReportPackFormModal>;

export const CreatingStartsAnEmptyPack: Story = {
  args: { api: buildPackApi([]) },
  play: async ({ args }) => {
    const dialog = within(await screen.findByRole("dialog", { name: "New report pack" }));
    await expect(requiredCaptions(document.body)).toEqual(["Name"]);
    await expect(dialog.getByRole("button", { name: "Create" })).toBeDisabled();
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Board pack");
    await userEvent.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(args.api!.create).toHaveBeenCalledWith({
      name: "Board pack", description: "", folder: "", definition: { schema_version: 1, entries: [] },
    }));
    await waitFor(() => expect(args.onSaved).toHaveBeenCalled());
  },
};

export const EditingRenamesWithoutTouchingTheDefinition: Story = {
  args: { api: buildPackApi([buildPackSummary()]), pack: buildPackSummary() },
  play: async ({ args }) => {
    const dialog = within(await screen.findByRole("dialog", { name: "Pack details" }));
    const name = dialog.getByRole("textbox", { name: "Name" });
    await userEvent.clear(name);
    await userEvent.type(name, "Renamed");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.api!.update).toHaveBeenCalledWith("pack-1", { name: "Renamed", description: "For the external team.", folder: "" }));
  },
};

export const ATakenNameIsShownInTheDialog: Story = {
  args: { api: buildPackApi([], { create: async () => { throw new Error("A pack called \"Taken\" already exists here."); } }) },
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "New report pack" }));
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Taken");
    await userEvent.click(dialog.getByRole("button", { name: "Create" }));
    await expect(await dialog.findByText(/already exists here/)).toBeInTheDocument();
  },
};

/** The folder is optional (so unmarked), chosen from the scope's folders and saved with the pack. */
export const FolderIsChosenFromTheTreeAndSaved: Story = {
  args: { api: buildPackApi([]) },
  play: async ({ args }) => {
    const dialog = within(await screen.findByRole("dialog", { name: "New report pack" }));
    await expect(requiredCaptions(document.body)).toEqual(["Name"]);
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Filed pack");
    const popover = await openFolderPopover(dialog);
    await userEvent.click(await popover.findByRole("radio", { name: "Quarterly" }));
    await userEvent.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(args.api!.create).toHaveBeenCalledWith(expect.objectContaining({ folder: "Handover/Quarterly" })));
  },
};
