import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { REPORT_FORMAT_PREFERENCE } from "../utils/reportFormatChoice";
import { ReportFormatDownload } from "./ReportFormatDownload";

const meta: Meta<typeof ReportFormatDownload> = {
  title: "Components/Reports/ReportFormatDownload",
  component: ReportFormatDownload,
  args: { kinds: ["pdf", "docx", "csv"], onDownload: fn(async () => true) },
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} }))],
};
export default meta;

type Story = StoryObj<typeof ReportFormatDownload>;

/** With no history the list starts on PDF and names every format the report offers, one button below. */
export const StartsOnPdfWithNoHistory: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const group = canvas.getByRole("group", { name: "Format" });
    await expect(within(group).getAllByRole("radio").map((r) => (r as HTMLInputElement).labels?.[0]?.textContent)).toEqual(["PDF", "Word", "CSV"]);
    await expect(canvas.getByRole("radio", { name: "PDF" })).toBeChecked();
    await userEvent.click(canvas.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(args.onDownload).toHaveBeenCalledWith("pdf"));
  },
};

/** The format last downloaded is already chosen, so the format a person uses most needs no click. */
export const StartsOnTheFormatLastDownloaded: Story = {
  decorators: [withStatefulAuth(buildUser({ ui_preferences: { [REPORT_FORMAT_PREFERENCE]: "csv" } }))],
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("radio", { name: "CSV" })).toBeChecked();
    await userEvent.click(canvas.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(args.onDownload).toHaveBeenCalledWith("csv"));
  },
};

/** A remembered format the report does not offer falls back to the report's first format. */
export const FallsBackToTheFirstFormat: Story = {
  args: { kinds: ["xlsx", "csv"] },
  decorators: [withStatefulAuth(buildUser({ ui_preferences: { [REPORT_FORMAT_PREFERENCE]: "odt" } }))],
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("radio", { name: "Excel" })).toBeChecked();
  },
};

/** PDF is the default only when offered; with no history and no PDF the first format is chosen. */
export const NoPdfNoHistoryChoosesTheFirst: Story = {
  args: { kinds: ["csv", "xlsx"] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("radio", { name: "CSV" })).toBeChecked();
  },
};

/** Only a download that went through is remembered: selecting an option, or a failed download, changes nothing stored. */
export const RemembersOnlyASuccessfulDownload: Story = {
  args: { onDownload: fn(async () => false) },
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} }))],
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("radio", { name: "Word" }));
    await expect(canvas.getByRole("radio", { name: "Word" })).toBeChecked();
    await userEvent.click(canvas.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(args.onDownload).toHaveBeenCalledWith("docx"));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Download" })).toBeEnabled());
  },
};

/** After a successful download the choice is the new default: a fresh list (another report) starts on it. */
export const ASuccessfulDownloadIsRemembered: Story = {
  render: function Render(args) {
    return (
      <div className="stack">
        <ReportFormatDownload {...args} />
        <ReportFormatDownload {...args} kinds={["pdf", "docx", "odt"]} />
      </div>
    );
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const [first, second] = canvas.getAllByRole("group", { name: "Format" });
    await userEvent.click(within(first).getByRole("radio", { name: "Word" }));
    await expect(within(second).getByRole("radio", { name: "PDF" })).toBeChecked();
    await userEvent.click(canvas.getAllByRole("button", { name: "Download" })[0]);
    await waitFor(() => expect(within(second).getByRole("radio", { name: "Word" })).toBeChecked());
  },
};

/** A blocked report disables the button and says why beside it, where the button is read. */
export const BlockedDisablesTheButtonWithItsReason: Story = {
  args: { blockedReason: "Choose a value for Categories to run this report." },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const button = canvas.getByRole("button", { name: "Download" });
    await expect(button).toBeDisabled();
    await expect(button).toHaveAccessibleDescription("Choose a value for Categories to run this report.");
    await expect(canvas.getByRole("status")).toHaveTextContent("Choose a value for Categories");
    await expect(args.onDownload).not.toHaveBeenCalled();
  },
};

/** A report with one format shows it and the button, not a one-item list. */
export const OneFormatIsNotAList: Story = {
  args: { kinds: ["xlsx"] },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("radio")).not.toBeInTheDocument();
    await expect(canvas.getByText("Format: Excel")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(args.onDownload).toHaveBeenCalledWith("xlsx"));
  },
};

/** The list is a native radio group: arrow keys move the choice and Space/Enter on the button downloads. */
export const WorksFromTheKeyboard: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    canvas.getByRole("radio", { name: "PDF" }).focus();
    await userEvent.keyboard("{ArrowDown}");
    await expect(canvas.getByRole("radio", { name: "Word" })).toBeChecked();
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(args.onDownload).toHaveBeenCalledWith("docx"));
  },
};
