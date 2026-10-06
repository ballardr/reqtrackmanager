import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ReportBreakdown, ReportMetric } from "../api/reports";
import { buildReportCatalogueEntry } from "../testing/reportFixtures";
import { withRouter } from "../testing/storybook-helpers";
import { ReportFigureProjectsDialog } from "./ReportFigureProjectsDialog";

const entry = buildReportCatalogueEntry({
  scope: "organization", module_key: "context_strategy", supports_include_children: false, supports_project_filter: true,
  path: "/api/v1/orgs/org-1/modules/context_strategy/reports/pain-point-prioritisation",
  breakdown_path: "/api/v1/orgs/org-1/modules/context_strategy/reports/pain-point-prioritisation/by-project",
});
const link = { kind: "module" as const, target: "pain-points", query: { blocker: "1" }, section: null };
const metric: ReportMetric = { label: "Blockers", value: 3, gap: true, group: "Pain Point prioritisation", link };

const breakdown: ReportBreakdown = {
  generated_at: "2026-10-06T09:30:00Z",
  truncated: false,
  projects: [
    { project_id: "p-low", project_name: "Borealis", metrics: [{ ...metric, value: 1 }] },
    { project_id: "p-zero", project_name: "Atlas", metrics: [{ ...metric, value: 0 }] },
    { project_id: "p-high", project_name: "Cascade", metrics: [{ ...metric, value: 2 }] },
  ],
};

const meta: Meta<typeof ReportFigureProjectsDialog> = {
  title: "Components/Reports/ReportFigureProjectsDialog",
  component: ReportFigureProjectsDialog,
  decorators: [withRouter("/")],
  args: { entry, values: { rollup: "weighted_average" }, metric, onClose: fn() },
};
export default meta;

type Story = StoryObj<typeof ReportFigureProjectsDialog>;

/** Projects are listed biggest first, each a link to its own filtered page; a zero is muted and not a link. */
export const ListsProjectsWithTheirNumbers: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(breakdown);
  },
  play: async ({ canvasElement }) => {
    const dialog = within(canvasElement.ownerDocument.body);
    await waitFor(() => expect(dialog.getByText("Cascade")).toBeInTheDocument());
    const names = dialog.getAllByText(/^(Cascade|Borealis|Atlas)$/).map((n) => n.textContent);
    await expect(names).toEqual(["Cascade", "Borealis", "Atlas"]);
    await expect(dialog.getByRole("link", { name: /Cascade/ })).toHaveAttribute(
      "href", "/projects/p-high/modules/context_strategy/pain-points?blocker=1",
    );
    await expect(dialog.queryByRole("link", { name: /Atlas/ })).not.toBeInTheDocument();
    await expect(dialog.getByRole("dialog", { name: "Blockers by project" })).toBeInTheDocument();
  },
};

/** Following a project closes the dialog. */
export const FollowingAProjectClosesTheDialog: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(breakdown);
  },
  play: async ({ canvasElement, args }) => {
    const dialog = within(canvasElement.ownerDocument.body);
    await userEvent.click(await dialog.findByRole("link", { name: /Borealis/ }));
    await expect(args.onClose).toHaveBeenCalled();
  },
};

export const ShowsAnErrorWhenTheBreakdownFails: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new Error("boom"));
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement.ownerDocument.body).findByRole("alert")).toBeInTheDocument();
  },
};
