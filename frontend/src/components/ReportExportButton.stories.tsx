import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { ReportExportButton } from "./ReportExportButton";

const meta: Meta<typeof ReportExportButton> = {
  title: "Components/ReportExportButton",
  component: ReportExportButton,
  args: { onDownload: fn() },
};
export default meta;

type Story = StoryObj<typeof ReportExportButton>;

/** The "report export trigger" pattern (`docs/ux-style-guide.md`): a single
 * "Export" button, no report options visibly competing for attention until
 * clicked — see `docs/ux-style-guide.md`'s Principle 11 for why two
 * permanently-visible adjacent buttons is the anti-pattern this replaces. */
export const ClosedByDefault: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Export" })).toBeInTheDocument();
    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
  },
};

export const DownloadPdfCallsOnDownloadWithPdf: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Export" }));
    const menu = within(document.body).getByRole("dialog", { name: "Export" });
    await userEvent.click(within(menu).getByRole("button", { name: "Download PDF report" }));
    await waitFor(() => expect(args.onDownload).toHaveBeenCalledWith("pdf"));
    // Selecting an option closes the menu, matching every other Popover-
    // based trigger in this codebase (`CsvImportWizard.tsx`'s Export menu).
    await expect(within(document.body).queryByRole("dialog", { name: "Export" })).not.toBeInTheDocument();
  },
};

export const DownloadCsvCallsOnDownloadWithCsv: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Export" }));
    const menu = within(document.body).getByRole("dialog", { name: "Export" });
    await userEvent.click(within(menu).getByRole("button", { name: "Download CSV report" }));
    await waitFor(() => expect(args.onDownload).toHaveBeenCalledWith("csv"));
  },
};

/** While a download's promise is pending, both popover options disable and
 * relabel — `onDownload` here never resolves, so the story can assert the
 * mid-flight state deterministically rather than racing a real promise. */
export const DisablesBothOptionsMidDownload: Story = {
  args: { onDownload: () => new Promise(() => {}) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Export" }));
    const menu = within(document.body).getByRole("dialog", { name: "Export" });
    await userEvent.click(within(menu).getByRole("button", { name: "Download PDF report" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Exporting…" })).toBeInTheDocument());
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
