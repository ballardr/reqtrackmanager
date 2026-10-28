import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, screen, spyOn, userEvent, within } from "storybook/test";

import { api } from "../api/client";
import { buildReportCatalogueEntry, buildReportResult } from "../testing/reportFixtures";
import { buildProject, buildUser, withRouter, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { ReportsMenuButton } from "./ReportsMenuButton";

function mockApis() {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/report-catalogue")) return [buildReportCatalogueEntry({ folder: "Fixture Module" })];
    if (path.includes("/report-templates") || path.includes("/report-placements") || path.includes("/report-packs")) return [];
    if (path.startsWith("/api/v1/report-runs")) return [];
    if (path.includes("/components") || path.includes("/categories") || path.includes("/resources")) return [];
    return buildReportResult({ title: "Fixture report" });
  });
}

const meta: Meta<typeof ReportsMenuButton> = {
  title: "Components/Reports/ReportsMenuButton",
  component: ReportsMenuButton,
  args: { scope: { kind: "project", id: "project-1" }, organizationId: "org-1", project: buildProject({ id: "project-1" }) },
  decorators: [withToast(), withStatefulAuth(buildUser({ ui_preferences: {} }))],
  beforeEach: mockApis,
};
export default meta;

type Story = StoryObj<typeof ReportsMenuButton>;

/** The menu offers the two views; choosing one opens the dialog on it, and Escape closes it again. */
export const OpensTheDialogOnEitherView: Story = {
  decorators: [withRouter("/projects/project-1", "/projects/:projectId")],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Reports" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Background reports…" }));
    await expect(await screen.findByRole("dialog", { name: "Background reports" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Reports" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Choose a report…" }));
    await expect(await screen.findByRole("dialog", { name: "Reports" })).toBeInTheDocument();
  },
};

/** A link that carries `reports=choose` (a report figure that points at another report) opens the dialog on that report. */
export const ALinkOpensTheDialogOnAReport: Story = {
  decorators: [withRouter("/projects/project-1?reports=choose&report=fixture-report", "/projects/:projectId")],
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "Reports" }));
    await expect(await dialog.findByText(/generated/)).toBeInTheDocument();
  },
};
