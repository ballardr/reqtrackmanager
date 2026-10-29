import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, screen, spyOn, within } from "storybook/test";

import { api, ApiError } from "../api/client";
import { buildReportRun } from "../testing/reportRunFixtures";
import { withRouter, withToast } from "../testing/storybook-helpers";
import { ReportRunPage } from "./ReportRunPage";

const meta: Meta<typeof ReportRunPage> = {
  title: "Pages/ReportRunPage",
  component: ReportRunPage,
  decorators: [withRouter("/report-runs/run-1", "/report-runs/:runId"), withToast()],
};
export default meta;

type Story = StoryObj<typeof ReportRunPage>;

/** A notification link lands on the report in a dialog. */
export const ShowsTheReport: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(buildReportRun());
  },
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Quarterly review" }));
    await expect(dialog.getByRole("button", { name: "Download" })).toBeInTheDocument();
  },
};

/** An expired report offers Generate again from the same link. */
export const AnExpiredReportOffersGenerateAgain: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(buildReportRun({ status: "expired", output_size: null }));
  },
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Quarterly review" }));
    await expect(dialog.getByRole("button", { name: "Generate again" })).toBeInTheDocument();
  },
};

/** Someone else's run, or one that is gone, shows the same short message. */
export const AnUnknownReportSaysSo: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new ApiError(404, "Report not found."));
  },
  play: async () => {
    await expect(await screen.findByRole("alert")).toHaveTextContent("This report is not in your list of background reports.");
  },
};
