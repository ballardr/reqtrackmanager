import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { buildReportRun } from "../testing/reportRunFixtures";
import { ReportRunsIndicator } from "./ReportRunsIndicator";

const meta: Meta<typeof ReportRunsIndicator> = {
  title: "Components/Reports/ReportRunsIndicator",
  component: ReportRunsIndicator,
};
export default meta;

type Story = StoryObj<typeof ReportRunsIndicator>;

/** With nothing in progress the indicator is not drawn. */
export const HiddenWhenNothingIsInProgress: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([]);
  },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/api/v1/report-runs?active=true"));
    await expect(within(canvasElement).queryByRole("button")).not.toBeInTheDocument();
  },
};

/** The clock shows the count, and its popover lists each report with its state and offers nothing else. */
export const ListsTheReportsBeingPrepared: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([
      buildReportRun({ id: "r-1", layout_name: "Waiting report", status: "queued" }),
      buildReportRun({ id: "r-2", layout_name: "Busy report", format: "docx", status: "running" }),
    ]);
  },
  play: async ({ canvasElement }) => {
    const button = await within(canvasElement).findByRole("button", { name: "2 reports being prepared" });
    await userEvent.click(button);
    const popover = within(await within(document.body).findByRole("dialog", { name: "Reports being prepared" }));
    await expect(popover.getByText("Waiting report")).toBeInTheDocument();
    await expect(popover.getByText("Busy report")).toBeInTheDocument();
    await expect(popover.getByText(/Preparing · requested/)).toBeInTheDocument();
    await expect(popover.queryByRole("button", { name: /Download|Delete|Cancel/ })).not.toBeInTheDocument();
  },
};
