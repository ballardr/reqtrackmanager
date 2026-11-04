import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { buildReportRun } from "../testing/reportRunFixtures";
import { withToast } from "../testing/storybook-helpers";
import { ReportRunDialog } from "./ReportRunDialog";

const meta: Meta<typeof ReportRunDialog> = {
  title: "Components/Reports/ReportRunDialog",
  component: ReportRunDialog,
  args: { initial: buildReportRun(), onClose: fn() },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof ReportRunDialog>;

/** A ready report shows its size and expiry and offers Download, and no Generate again. */
export const Ready: Story = {
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Quarterly review" }));
    await expect(dialog.getByText("Ready")).toBeInTheDocument();
    await expect(dialog.getByText(/PDF · /)).toBeInTheDocument();
    await expect(dialog.getByText(/You can download it until/)).toBeInTheDocument();
    await expect(dialog.getByRole("button", { name: "Download" })).toBeInTheDocument();
    await expect(dialog.queryByRole("button", { name: "Generate again" })).not.toBeInTheDocument();
  },
};

/** Download fetches the stored file. */
export const DownloadsTheFile: Story = {
  beforeEach: () => {
    spyOn(api, "getForBlob").mockResolvedValue(new Blob(["pdf"]));
  },
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Quarterly review" }));
    await userEvent.click(dialog.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith("/api/v1/report-runs/run-1/download"));
  },
};

/** A report still being prepared says so and offers neither Download nor Generate again. */
export const StillBeingPrepared: Story = {
  args: { initial: buildReportRun({ status: "running", expires_at: null, output_filename: null, output_size: null }) },
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Quarterly review" }));
    await expect(dialog.getByText(/still being prepared/)).toBeInTheDocument();
    await expect(dialog.queryByRole("button", { name: "Download" })).not.toBeInTheDocument();
    await expect(dialog.queryByRole("button", { name: "Generate again" })).not.toBeInTheDocument();
  },
};

/** A report whose file was removed explains it and offers Generate again, which queues a fresh run. */
export const ExpiredOffersGenerateAgain: Story = {
  args: { initial: buildReportRun({ status: "expired", output_size: null }) },
  beforeEach: () => {
    spyOn(api, "post").mockResolvedValue({ run: buildReportRun({ id: "run-2", status: "queued" }), definition_changed: true });
  },
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Quarterly review" }));
    await expect(dialog.getByText(/removed after its retention period/)).toBeInTheDocument();
    await expect(dialog.getByText(/not a copy of the old file/)).toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: "Generate again" }));
    await expect(await dialog.findByText(/fresh run of this report has been queued/)).toBeInTheDocument();
    await expect(dialog.getByText(/edited since the earlier run/)).toBeInTheDocument();
    await expect(api.post).toHaveBeenCalledWith("/api/v1/report-runs/run-1/again");
  },
};

/** A failed report shows its reason and offers Generate again. */
export const FailedShowsTheReason: Story = {
  args: {
    initial: buildReportRun({
      status: "failed", expires_at: null, output_filename: null, output_size: null, error: "The report took too long to produce.",
    }),
  },
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Quarterly review" }));
    await expect(dialog.getByRole("alert")).toHaveTextContent("The report took too long to produce.");
    await expect(dialog.getByRole("button", { name: "Generate again" })).toBeInTheDocument();
  },
};

/** A refusal from the server (the layout is gone) is shown as an error and the button stays. */
export const GenerateAgainRefused: Story = {
  args: { initial: buildReportRun({ status: "expired", output_size: null }) },
  beforeEach: () => {
    spyOn(api, "post").mockRejectedValue(new Error("This report no longer exists."));
  },
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Quarterly review" }));
    await userEvent.click(dialog.getByRole("button", { name: "Generate again" }));
    await expect(await screen.findByText("This report no longer exists.")).toBeInTheDocument();
    await expect(dialog.getByRole("button", { name: "Generate again" })).toBeEnabled();
  },
};
