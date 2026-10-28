import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ReportCatalogueEntry } from "../api/reports";
import { buildReportCatalogueEntry, buildReportResult } from "../testing/reportFixtures";
import { buildUser, withRouter, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { ReportDownloadDialog } from "./ReportDownloadDialog";

const forRequirements = buildReportCatalogueEntry({
  key: "r1", slug: "requirement-coverage", title: "Requirement coverage", description: "Coverage of requirements.",
  folder: "Requirements", record_types: ["requirement"],
  path: "/api/v1/projects/project-1/modules/fixture_report_module/reports/requirement-coverage",
});
const forEngagements = buildReportCatalogueEntry({
  key: "e1", slug: "engagement-yield", title: "Engagement yield", description: "Research yield.",
  folder: "Research", record_types: ["engagement", "persona"],
  path: "/api/v1/projects/project-1/modules/fixture_report_module/reports/engagement-yield",
});
const forBoth = buildReportCatalogueEntry({
  key: "b1", slug: "trace-pack", title: "Decision trace", description: "Decisions and requirements.",
  folder: "Requirements", record_types: ["decision", "requirement"],
  path: "/api/v1/projects/project-1/modules/fixture_report_module/reports/trace-pack",
});

function mockApis(entries: ReportCatalogueEntry[]) {
  return () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/report-catalogue")) return entries;
      if (path.includes("/report-templates") || path.includes("/report-placements")) return [];
      if (path.startsWith("/api/v1/report-runs")) return [];
      return buildReportResult({ title: "Requirement coverage" });
    });
  };
}

const meta: Meta<typeof ReportDownloadDialog> = {
  title: "Components/Reports/ReportDownloadDialog",
  component: ReportDownloadDialog,
  args: {
    projectId: "project-1", organizationId: "org-1", ownedByOrganization: false, recordType: "requirement",
    recordLabel: "Requirements", onClose: fn(),
  },
  decorators: [withRouter("/projects/project-1/requirements", "/projects/:projectId/requirements"), withToast(), withStatefulAuth(buildUser({ ui_preferences: {} }))],
  beforeEach: mockApis([forRequirements, forEngagements, forBoth]),
};
export default meta;

type Story = StoryObj<typeof ReportDownloadDialog>;

/** Only reports that use the list's record type are offered: an engagement report is not on a requirements list. The folders open collapsed the first time. */
export const OffersOnlyReportsThatUseTheType: Story = {
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Download report" }));
    await userEvent.click(await dialog.findByRole("button", { name: "Expand Requirements" }));
    await expect(await dialog.findByRole("button", { name: /^Requirement coverage/ })).toBeInTheDocument();
    await expect(dialog.getByRole("button", { name: /^Decision trace/ })).toBeInTheDocument();
    await expect(dialog.queryByText(/Engagement yield/)).not.toBeInTheDocument();
  },
};

/** Choosing a report shows it for download, with a way back to the choice. */
export const ChoosingAReportRunsItAndCanGoBack: Story = {
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Download report" }));
    await userEvent.click(await dialog.findByRole("button", { name: "Expand Requirements" }));
    await userEvent.click(await dialog.findByRole("button", { name: /^Requirement coverage/ }));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining("/reports/requirement-coverage?format=json")));
    await userEvent.click(dialog.getByRole("button", { name: "Choose another report" }));
    await expect(await dialog.findByRole("button", { name: /^Decision trace/ })).toBeInTheDocument();
  },
};

/** A type no report uses says so instead of showing an empty picker. */
export const SaysWhenNoReportUsesTheType: Story = {
  args: { recordType: "glossary_term", recordLabel: "Glossary terms" },
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Download report" }));
    await expect(await dialog.findByText("No report uses glossary terms.")).toBeInTheDocument();
  },
};

/** An organisation's own list reads the organisation catalogue. */
export const AnOrganisationListUsesTheOrganisationCatalogue: Story = {
  args: { projectId: undefined, ownedByOrganization: true, recordType: "engagement", recordLabel: "Engagements" },
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Download report" }));
    await userEvent.click(await dialog.findByRole("button", { name: "Expand Research" }));
    await expect(await dialog.findByRole("button", { name: /^Engagement yield/ })).toBeInTheDocument();
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/api/v1/orgs/org-1/report-catalogue"));
  },
};
