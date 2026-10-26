import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ReportRun } from "../api/reports";
import { withToast } from "../testing/storybook-helpers";
import { ReportRunsPanel } from "./ReportRunsPanel";

function run(over: Partial<ReportRun>): ReportRun {
  return {
    id: "run-1", organization_id: "org-1", project_id: "project-1", scope: "project", layout_name: "Quarterly review",
    layout_version: 3, format: "pdf", status: "ready", created_at: "2026-10-27T01:00:00Z", started_at: "2026-10-27T01:00:05Z",
    finished_at: "2026-10-27T01:02:00Z", expires_at: "2026-11-03T01:02:00Z", output_filename: "atlas-quarterly-review.pdf",
    output_size: 2_400_000, error: null, ...over,
  };
}

const meta: Meta<typeof ReportRunsPanel> = {
  title: "Components/Reports/ReportRunsPanel",
  component: ReportRunsPanel,
  args: { organizationId: "org-1" },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof ReportRunsPanel>;

/** Nothing is shown until the person has a background report. */
export const RendersNothingWithoutRuns: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([]);
  },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("region")).not.toBeInTheDocument();
  },
};

/** Each state is named through its label and offers only the actions that apply to it. */
export const ShowsEachState: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([
      run({ id: "r-ready", layout_name: "Ready report" }),
      run({ id: "r-queued", layout_name: "Waiting report", status: "queued", expires_at: null, output_filename: null, output_size: null }),
      run({ id: "r-failed", layout_name: "Failed report", status: "failed", expires_at: null, output_filename: null, output_size: null, error: "The report took too long to produce." }),
      run({ id: "r-expired", layout_name: "Old report", status: "expired", output_size: null }),
    ]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const region = await canvas.findByRole("region", { name: "Background reports" });
    await expect(within(region).getByText("Ready")).toBeInTheDocument();
    await expect(within(region).getByText("Waiting")).toBeInTheDocument();
    await expect(within(region).getByText("Failed")).toBeInTheDocument();
    await expect(within(region).getByText("Expired")).toBeInTheDocument();
    await expect(within(region).getByText("The report took too long to produce.")).toBeInTheDocument();
    await expect(canvas.getAllByRole("button", { name: /^Download / })).toHaveLength(1);
    await expect(canvas.getByRole("button", { name: "Cancel Waiting report" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Delete file Ready report" })).toBeInTheDocument();
  },
};

/** Download saves the file named by the server and confirms with a toast. */
export const DownloadSavesTheFile: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([run({})]);
    spyOn(api, "getForBlob").mockResolvedValue(new Blob(["%PDF"]));
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Download Quarterly review" }));
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith("/api/v1/report-runs/run-1/download"));
    await waitFor(() => expect(within(document.body).getByText("Downloaded Quarterly review.")).toBeInTheDocument());
  },
};

/** Deleting the stored file asks first (Tier 1), then reloads the list. */
export const DeleteFileAsksFirst: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([run({})]);
    spyOn(api, "delete").mockResolvedValue(run({ status: "expired", output_size: null }));
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Delete file Quarterly review" }));
    await expect(api.delete).not.toHaveBeenCalled();
    const dialog = within(document.body).getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete file" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/api/v1/report-runs/run-1"));
    await waitFor(() => expect(within(document.body).getByText("The report file was deleted.")).toBeInTheDocument());
  },
};

/** A download that is refused (the file expired meanwhile) reports it and reloads the list. */
export const DownloadFailureShowsToast: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([run({})]);
    spyOn(api, "getForBlob").mockRejectedValue(new Error("This report is no longer available."));
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Download Quarterly review" }));
    await waitFor(() => expect(within(document.body).getByText("This report is no longer available.")).toBeInTheDocument());
  },
};

/** A failed list load is shown inline. */
export const LoadFailureShowsError: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new Error("boom"));
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("alert")).toBeInTheDocument();
  },
};
