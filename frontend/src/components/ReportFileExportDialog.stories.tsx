import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, userEvent, waitFor, within } from "storybook/test";

import { buildFileApi } from "../testing/reportFileFixtures";
import { withToast } from "../testing/storybook-helpers";
import { ReportFileExportDialog } from "./ReportFileExportDialog";

/** Exports the chosen layouts and packs as a `.zip` report file. */
const meta: Meta<typeof ReportFileExportDialog> = {
  title: "Components/Reports/ReportFileExportDialog",
  component: ReportFileExportDialog,
  decorators: [withToast()],
  args: { api: buildFileApi(), layoutIds: ["l1"], packIds: [], onClose: fn() },
};
export default meta;

type Story = StoryObj<typeof ReportFileExportDialog>;

const dialog = async (name: string) => within(await screen.findByRole("dialog", { name }));

export const ALayoutExportsItsCurrentVersion: Story = {
  play: async ({ args }) => {
    const d = await dialog("Export 1 report as a file");
    await expect(d.getByRole("checkbox", { name: "Include earlier versions" })).not.toBeChecked();
    await expect(d.queryByRole("checkbox", { name: "Include the layouts the packs use" })).not.toBeInTheDocument();
    await userEvent.click(d.getByRole("button", { name: "Export" }));
    await waitFor(() => expect(args.onClose).toHaveBeenCalled());
    await expect(args.api.exportFile).toHaveBeenCalledWith({
      layout_ids: ["l1"], pack_ids: [], include_history: false, include_pack_layouts: true,
    });
  },
};

export const APackOffersItsLayoutsAndHistoryCanBeAdded: Story = {
  args: { layoutIds: ["l1"], packIds: ["p1"] },
  play: async ({ args }) => {
    const d = await dialog("Export 2 reports as a file");
    await userEvent.click(d.getByRole("checkbox", { name: "Include earlier versions" }));
    await userEvent.click(d.getByRole("checkbox", { name: "Include the layouts the packs use" }));
    await userEvent.click(d.getByRole("button", { name: "Export" }));
    await waitFor(() => expect(args.api.exportFile).toHaveBeenCalledWith({
      layout_ids: ["l1"], pack_ids: ["p1"], include_history: true, include_pack_layouts: false,
    }));
  },
};

export const AFailedExportShowsTheErrorAndStaysOpen: Story = {
  args: { api: { ...buildFileApi(), exportFile: fn(async () => { throw new Error("A chosen report is not available here."); }) } },
  play: async ({ args }) => {
    const d = await dialog("Export 1 report as a file");
    await userEvent.click(d.getByRole("button", { name: "Export" }));
    await expect(await d.findByText("A chosen report is not available here.")).toBeInTheDocument();
    await expect(args.onClose).not.toHaveBeenCalled();
  },
};
