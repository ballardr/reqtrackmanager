import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ReportPackSummary } from "../api/reportPacks";
import { buildProject } from "../testing/storybook-helpers";
import { buildForm, buildPackSummary } from "../testing/reportPackFixtures";
import { buildReportCatalogueEntry, buildReportResult } from "../testing/reportFixtures";
import { buildUser, withRouter, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { ReportsDialog } from "./ReportsDialog";

const entry = buildReportCatalogueEntry({ folder: "Fixture Module" });

function mockApis(packs: ReportPackSummary[] = []) {
  return () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/report-catalogue")) return [entry];
      if (path.endsWith("/report-packs")) return packs;
      if (path.endsWith("/form")) return buildForm();
      if (path.includes("/report-templates") || path.includes("/report-placements")) return [];
      if (path.includes("/components") || path.includes("/categories") || path.includes("/resources")) return [];
      return buildReportResult({ title: "Fixture report" });
    });
  };
}

const meta: Meta<typeof ReportsDialog> = {
  title: "Components/Reports/ReportsDialog",
  component: ReportsDialog,
  args: {
    scope: { kind: "project", id: "project-1" }, organizationId: "org-1", project: buildProject({ id: "project-1" }),
    onClose: fn(),
  },
  decorators: [withRouter("/projects/project-1", "/projects/:projectId"), withToast(), withStatefulAuth(buildUser({ ui_preferences: {} }))],
  beforeEach: mockApis(),
};
export default meta;

type Story = StoryObj<typeof ReportsDialog>;

/** The requirement report is the first choice for a project and files under Platform; the catalogue's reports sit beside it. */
export const OffersTheRequirementReportAndTheCatalogue: Story = {
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Reports" }));
    await userEvent.click(await dialog.findByRole("button", { name: "Report: Requirements report" }));
    const picker = within(await screen.findByRole("dialog", { name: "Choose a report" }));
    await expect(picker.getByRole("button", { name: "Expand Platform" })).toBeInTheDocument();
    await expect(picker.getByRole("button", { name: "Expand Fixture Module" })).toBeInTheDocument();
  },
};

/** Choosing a catalogue report runs it in place, ready to download. */
export const ChoosingAReportRunsIt: Story = {
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Reports" }));
    await userEvent.click(await dialog.findByRole("button", { name: "Report: Requirements report" }));
    const picker = within(await screen.findByRole("dialog", { name: "Choose a report" }));
    await userEvent.click(picker.getByRole("button", { name: "Expand Fixture Module" }));
    await userEvent.click(picker.getByRole("button", { name: /^Fixture report/ }));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining("/reports/fixture-report?format=json")));
  },
};

/** An organisation's dialog has no requirement report: it opens on what its catalogue lists. */
export const AnOrganisationHasNoRequirementReport: Story = {
  args: { scope: { kind: "organization", id: "org-1" }, project: undefined },
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Reports" }));
    await expect(await dialog.findByText(/generated/)).toBeInTheDocument();
    await expect(dialog.queryByText(/Requirements report/)).not.toBeInTheDocument();
  },
};

const pack = buildPackSummary({ id: "pack-1", name: "Handover pack", folder: "Bundles" });

/** A project's dialog lists its report packs beside its reports. */
export const OffersReportPacksForAProject: Story = {
  beforeEach: mockApis([pack]),
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Reports" }));
    await userEvent.click(await dialog.findByRole("button", { name: "Report: Requirements report" }));
    const picker = within(await screen.findByRole("dialog", { name: "Choose a report" }));
    await userEvent.click(picker.getByRole("button", { name: "Expand Bundles" }));
    await expect(picker.getByRole("button", { name: /^Handover pack/ })).toBeInTheDocument();
  },
};

/** An organisation's dialog lists its report packs too. */
export const OffersReportPacksForAnOrganisation: Story = {
  args: { scope: { kind: "organization", id: "org-1" }, project: undefined },
  beforeEach: mockApis([pack]),
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Reports" }));
    await userEvent.click(await dialog.findByRole("button", { name: /^Report:/ }));
    const picker = within(await screen.findByRole("dialog", { name: "Choose a report" }));
    await userEvent.click(picker.getByRole("button", { name: "Expand Bundles" }));
    await expect(picker.getByRole("button", { name: /^Handover pack/ })).toBeInTheDocument();
  },
};
