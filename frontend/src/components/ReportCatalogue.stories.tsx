import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { buildReportCatalogueEntry, buildReportResult } from "../testing/reportFixtures";
import { withRouter, withToast } from "../testing/storybook-helpers";
import { ReportCatalogue } from "./ReportCatalogue";

const first = buildReportCatalogueEntry();
const second = buildReportCatalogueEntry({
  key: "f2", slug: "second-report", title: "Second report", description: "Another synthetic report.",
  path: "/api/v1/projects/project-1/modules/fixture_report_module/reports/second-report", params: [],
  supports_include_children: false,
});

function mockApis() {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/report-templates")) return [];
    return buildReportResult({ title: path.includes("second-report") ? "Second report" : "Fixture report" });
  });
}

const meta: Meta<typeof ReportCatalogue> = {
  title: "Components/Reports/ReportCatalogue",
  component: ReportCatalogue,
  args: { entries: [first, second], scope: { kind: "project", id: "project-1" }, organizationId: "org-1" },
  decorators: [withRouter("/projects/project-1/reports", "/projects/:projectId/reports"), withToast()],
  beforeEach: mockApis,
};
export default meta;

type Story = StoryObj<typeof ReportCatalogue>;

/** The first entry is selected and run; its description sits under the picker. */
export const SelectsFirstEntryByDefault: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("Report")).toHaveValue("fixture-report");
    await expect(canvas.getByText(first.description)).toBeInTheDocument();
    await waitFor(() => expect(canvas.getByRole("region", { name: "Items" })).toBeInTheDocument());
  },
};

/** Switching the picker shows the other report and runs it. */
export const SwitchingReportRunsIt: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByLabelText("Report"), "second-report");
    await expect(canvas.getByText(second.description)).toBeInTheDocument();
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining("/reports/second-report?format=json")));
  },
};

/** An extra (non-catalogue) entry is listed first and renders host content. */
export const ExtraEntryIsOfferedFirst: Story = {
  args: {
    extraEntries: [{ key: "requirements", title: "Requirements report", description: "Host report.", render: () => <p>Host content</p> }],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const picker = canvas.getByLabelText("Report");
    await expect(picker).toHaveValue("requirements");
    await expect(canvas.getByText("Host content")).toBeInTheDocument();
    const options = within(picker).getAllByRole("option").map((o) => o.textContent);
    await expect(options).toEqual(["Requirements report", "Fixture report", "Second report"]);
  },
};

/** With one entry there is nothing to pick between, so no picker is drawn. */
export const SingleEntryHasNoPicker: Story = {
  args: { entries: [first] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByLabelText("Report")).not.toBeInTheDocument();
    await waitFor(() => expect(canvas.getByRole("region", { name: "Items" })).toBeInTheDocument());
  },
};

/** Entries from several modules are prefixed with the module's name. */
export const PrefixesModuleNameWhenSeveralModules: Story = {
  args: { entries: [first, buildReportCatalogueEntry({ ...second, module_key: "other_module", module_name: "Other Module" })] },
  play: async ({ canvasElement }) => {
    const options = within(within(canvasElement).getByLabelText("Report")).getAllByRole("option").map((o) => o.textContent);
    await expect(options).toEqual(["Fixture Module: Fixture report", "Other Module: Second report"]);
  },
};

export const NoReportsMessage: Story = {
  args: { entries: [] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("No reports are available.")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...SelectsFirstEntryByDefault, globals: { theme: "light" } };
export const DarkTheme: Story = { ...SelectsFirstEntryByDefault, globals: { theme: "dark" } };
