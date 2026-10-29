import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ReportPackSummary } from "../api/reportPacks";
import type { ReportCatalogueEntry } from "../api/reports";
import { buildForm, buildPackSummary, buildPreview } from "../testing/reportPackFixtures";
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

const summary = buildReportCatalogueEntry({
  key: "r8", slug: "summary", title: "Summary pack", description: "Read on screen.", folder: "Requirements",
  record_types: ["requirement"], view_only: true,
  path: "/api/v1/projects/project-1/modules/fixture_report_module/reports/summary",
});

const requirementsPack = buildPackSummary({ id: "pack-r", name: "Handover pack", folder: "Bundles", record_types: ["requirement"] });
const engagementsPack = buildPackSummary({ id: "pack-e", name: "Research pack", folder: "Bundles", record_types: ["engagement"] });

function mockApis(entries: ReportCatalogueEntry[], packs: ReportPackSummary[] = []) {
  return () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/report-catalogue")) return entries;
      if (path.endsWith("/report-packs")) return packs;
      if (path.endsWith("/form")) return buildForm();
      if (path.includes("/report-placements")) return [];
      if (path.startsWith("/api/v1/report-runs")) return [];
      if (path === "/api/v1/projects/project-1") return { name: "Apollo" };
      if (path === "/api/v1/orgs/org-1") return { name: "Acme" };
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
  beforeEach: mockApis([forRequirements, forEngagements, forBoth, summary]),
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

/** A report meant to be read on screen is not offered for download, though it names the list's record type. */
export const LeavesOutViewOnlyReports: Story = {
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Download report" }));
    await userEvent.click(await dialog.findByRole("button", { name: "Expand Requirements" }));
    await expect(await dialog.findByRole("button", { name: /^Requirement coverage/ })).toBeInTheDocument();
    await expect(dialog.queryByText(/Summary pack/)).not.toBeInTheDocument();
  },
};

/** Choosing a report moves to step 2: the report and project are named, nothing is run for the screen, and Back returns to step 1. */
export const ChoosingAReportShowsStepTwoAndCanGoBack: Story = {
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Download report" }));
    const steps = dialog.getByRole("list", { name: "Download steps" });
    await expect(within(steps).getByText("Choose a report").closest("li")).toHaveAttribute("aria-current", "step");
    await userEvent.click(await dialog.findByRole("button", { name: "Expand Requirements" }));
    await userEvent.click(await dialog.findByRole("button", { name: /^Requirement coverage/ }));
    await expect(within(steps).getByText("Configure and download").closest("li")).toHaveAttribute("aria-current", "step");
    await expect(await dialog.findByText("Apollo")).toBeInTheDocument();
    await expect(dialog.getByText("Requirement coverage")).toBeInTheDocument();
    await expect(dialog.getByRole("button", { name: "Export" })).toBeInTheDocument();
    // The report is not previewed, so it is never fetched for the screen.
    await expect(api.get).not.toHaveBeenCalledWith(expect.stringContaining("/reports/requirement-coverage?format=json"));
    await userEvent.click(dialog.getByRole("button", { name: "Back" }));
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
    await userEvent.click(await dialog.findByRole("button", { name: /^Engagement yield/ }));
    await expect(await dialog.findByText("Acme")).toBeInTheDocument();
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/api/v1/orgs/org-1/report-catalogue"));
  },
};

/** A pack is offered when a report in it reads the list's type, beside the reports, and one that reads other types is not. */
export const OffersPacksThatReadTheType: Story = {
  beforeEach: mockApis([forRequirements], [requirementsPack, engagementsPack]),
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Download report" }));
    await userEvent.click(await dialog.findByRole("button", { name: "Expand Bundles" }));
    await expect(await dialog.findByRole("button", { name: /^Handover pack/ })).toBeInTheDocument();
    await expect(dialog.queryByText(/Research pack/)).not.toBeInTheDocument();
  },
};

/** Choosing a pack moves to step 2, which names the pack and the project and offers the zip. */
export const ChoosingAPackShowsItsRunForm: Story = {
  beforeEach: () => {
    mockApis([], [requirementsPack])();
    spyOn(api, "post").mockResolvedValue(buildPreview());
  },
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Download report" }));
    await userEvent.click(await dialog.findByRole("button", { name: "Expand Bundles" }));
    await userEvent.click(await dialog.findByRole("button", { name: /^Handover pack/ }));
    await expect(await dialog.findByText("Apollo")).toBeInTheDocument();
    await expect(await dialog.findByRole("button", { name: "Download zip" })).toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: "Back" }));
    await expect(await dialog.findByRole("button", { name: /^Handover pack/ })).toBeInTheDocument();
  },
};

/** When only a pack reads the type, the dialog still lists it instead of saying no report uses the type. */
export const ListsAPackWhenNoReportUsesTheType: Story = {
  beforeEach: mockApis([], [requirementsPack]),
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Download report" }));
    await userEvent.click(await dialog.findByRole("button", { name: "Expand Bundles" }));
    await expect(await dialog.findByRole("button", { name: /^Handover pack/ })).toBeInTheDocument();
    await expect(dialog.queryByText(/No report uses/)).not.toBeInTheDocument();
  },
};
