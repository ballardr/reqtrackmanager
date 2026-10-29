import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, userEvent, waitFor, within } from "storybook/test";

import { buildFolderApi } from "../testing/reportFolderFixtures";
import { withToast } from "../testing/storybook-helpers";
import { ReportMoveDialog } from "./ReportMoveDialog";

/** The dialog that moves one report to a folder from the Report setup list. */
const meta: Meta<typeof ReportMoveDialog> = {
  title: "Components/Reports/ReportMoveDialog",
  component: ReportMoveDialog,
  decorators: [withToast()],
  args: {
    title: "Decision register", folder: "Decision Management", folders: ["Decision Management"], folderApi: buildFolderApi(),
    onChanged: fn(), onClose: fn(), onSave: fn(async () => undefined),
  },
};
export default meta;

type Story = StoryObj<typeof ReportMoveDialog>;

export const OffersTheCurrentFolderAndMovesToAnother: Story = {
  play: async ({ args }) => {
    const dialog = within(await screen.findByRole("dialog", { name: "Move Decision register" }));
    await expect(await dialog.findByRole("radio", { name: "Decision Management" })).toBeChecked();
    await userEvent.click(await dialog.findByRole("radio", { name: "Handover" }));
    await userEvent.click(dialog.getByRole("button", { name: "Move" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith("Handover"));
  },
};

export const TheTopLevelIsAChoice: Story = {
  play: async ({ args }) => {
    const dialog = within(await screen.findByRole("dialog", { name: "Move Decision register" }));
    await userEvent.click(await dialog.findByRole("radio", { name: "Top level" }));
    await userEvent.click(dialog.getByRole("button", { name: "Move" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(""));
  },
};

export const AnOwnedReportNamesItsDefaultFolderInsteadOfTheTopLevel: Story = {
  args: { noneLabel: "No folder (the default)", folder: "" },
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Move Decision register" }));
    await expect(await dialog.findByRole("radio", { name: "No folder (the default)" })).toBeChecked();
    await expect(dialog.queryByRole("radio", { name: "Top level" })).not.toBeInTheDocument();
  },
};
