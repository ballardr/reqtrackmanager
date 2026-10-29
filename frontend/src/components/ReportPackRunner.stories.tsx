import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api, ApiError } from "../api/client";
import { buildCategoriesVariable, buildForm, buildPreview, buildRun, buildRunApi } from "../testing/reportPackFixtures";
import { withToast } from "../testing/storybook-helpers";
import { ReportPackRunner } from "./ReportPackRunner";

/** Runs one pack from the Reports page: variables, saved choices, the counts per report and the zip download. */
const meta: Meta<typeof ReportPackRunner> = {
  title: "Components/Reports/ReportPackRunner",
  component: ReportPackRunner,
  args: { name: "Handover pack" },
  decorators: [withToast()],
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([]);
    window.URL.createObjectURL = () => "blob:pack";
    window.URL.revokeObjectURL = () => undefined;
  },
};
export default meta;

type Story = StoryObj<typeof ReportPackRunner>;

const asyncRequired = () => new ApiError(409, "Too big", { code: "async_required" });

export const HoldsBackUntilTheRequiredVariableHasAValue: Story = {
  args: { api: buildRunApi() },
  play: async ({ canvasElement, args }) => {
    const view = within(canvasElement);
    await expect(await view.findByText(/Choose a value for Categories/)).toBeInTheDocument();
    await expect(view.getByRole("button", { name: "Download zip" })).toBeDisabled();
    await expect(args.api.preview).not.toHaveBeenCalled();
  },
};

export const ChoosingASavedSetFillsTheFormAndShowsWhatIsIncluded: Story = {
  args: { api: buildRunApi() },
  play: async ({ canvasElement, args }) => {
    const view = within(canvasElement);
    await userEvent.selectOptions(await view.findByRole("combobox", { name: /Saved choices/ }), "set-1");
    const table = await view.findByRole("table", { name: "What the zip will contain" });
    await expect(within(table).getByText("Requirements overview")).toBeInTheDocument();
    await expect(within(table).getByText("Its module is not enabled for this project.")).toBeInTheDocument();
    await expect(within(table).getByText("Not available")).toBeInTheDocument();
    await expect(view.getByText(/24 records in total/)).toBeInTheDocument();
    await expect(view.getByText(/1 report is not available/)).toBeInTheDocument();
    await waitFor(() => expect(args.api.preview).toHaveBeenCalledWith(expect.objectContaining({
      variables: { categories: ["Security"] }, variable_set_id: "set-1",
    })));
    await expect(view.getByRole("button", { name: "Download zip" })).toBeEnabled();
  },
};

export const DownloadingSendsTheSameValuesAsThePreview: Story = {
  args: { api: buildRunApi() },
  play: async ({ canvasElement, args }) => {
    const view = within(canvasElement);
    await userEvent.selectOptions(await view.findByRole("combobox", { name: /Saved choices/ }), "set-1");
    await view.findByRole("table", { name: "What the zip will contain" });
    await userEvent.click(view.getByRole("button", { name: "Download zip" }));
    await waitFor(() => expect(args.api.download).toHaveBeenCalledWith(expect.objectContaining({
      variables: { categories: ["Security"] }, variable_set_id: "set-1",
    })));
    await expect(await within(document.body).findByText("Downloaded Handover pack.")).toBeInTheDocument();
  },
};

export const APackTooBigToWaitForIsQueuedInTheBackground: Story = {
  args: { api: buildRunApi({ download: async () => { throw asyncRequired(); }, queue: fn(async () => buildRun()) }) },
  play: async ({ canvasElement, args }) => {
    const view = within(canvasElement);
    await userEvent.selectOptions(await view.findByRole("combobox", { name: /Saved choices/ }), "set-1");
    await view.findByRole("table", { name: "What the zip will contain" });
    await userEvent.click(view.getByRole("button", { name: "Download zip" }));
    await waitFor(() => expect(args.api.queue).toHaveBeenCalled());
    await expect(await within(document.body).findByText(/is being prepared in the background/)).toBeInTheDocument();
  },
};

export const NothingRunnableDisablesTheDownload: Story = {
  args: {
    api: buildRunApi({
      form: async () => buildForm({ variables: [buildCategoriesVariable({ default: ["Security"] })], sets: [] }),
      preview: async () => buildPreview({
        entries: [{ position: 1, kind: "layout", title: "Gone", format: "pdf", status: "not_available", reason: "No report layout of that name is available here.", records: 0, warnings: [] }],
        total_records: 0, not_available: 1,
      }),
    }),
  },
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await expect(await view.findByText("No report layout of that name is available here.")).toBeInTheDocument();
    await expect(view.getByRole("button", { name: "Download zip" })).toBeDisabled();
    await expect(view.queryByRole("combobox", { name: /Saved choices/ })).not.toBeInTheDocument();
  },
};

export const SaysThatVariablesNarrowAndDoNotLimitAccess: Story = {
  args: { api: buildRunApi({ form: async () => buildForm({ variables: [buildCategoriesVariable({ default: ["Security"] })] }) }) },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText(/Variables narrow what the reports show/)).toBeInTheDocument();
  },
};

export const AFailedLoadIsReported: Story = {
  args: { api: buildRunApi({ form: async () => { throw new Error("denied"); } }) },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("alert")).toHaveTextContent("This pack could not be loaded.");
  },
};
