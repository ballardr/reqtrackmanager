import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../../api/client";
import type { OrgDashboardLayout, OverviewWidget } from "../../api/types";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { OrgDashboardView } from "./OrgDashboardView";

const ORG_ID = "org-1";

const TILE: OverviewWidget = {
  id: "projects", type: "metric_tile", title: null, width: 3, height: 2, scope: null, visible: true,
  config: { metric: "org_project_count" },
};

function layout(overrides: Partial<OrgDashboardLayout["dashboard"]> = {}, widgets: OverviewWidget[] = [TILE]): OrgDashboardLayout {
  return {
    dashboard: { id: "overview", name: "Overview", is_default: true, restricted: false, viewers: [], can_manage: false, ...overrides },
    scope: "this", widgets, built_in: true,
  };
}

function mockApis(loaded: OrgDashboardLayout) {
  spyOn(api, "get").mockResolvedValue(loaded);
  spyOn(api, "post").mockResolvedValue({
    results: { projects: { state: "ok", unit: "count", label: "Projects", projects: 3, value: 3, breakdown: null } },
  });
}

/** One page of an organisation's overview dashboards, drawn through the shared widget grid. */
const meta: Meta<typeof OrgDashboardView> = {
  title: "Components/Overview/OrgDashboardView",
  component: OrgDashboardView,
  decorators: [withRouter("/"), withToast()],
  args: { orgId: ORG_ID, dashboardId: "overview" },
};
export default meta;

type Story = StoryObj<typeof OrgDashboardView>;

/** The figures of the page's widgets arrive in one batched request to the page's own endpoint. */
export const ShowsTheFiguresFromOneRequest: Story = {
  beforeEach: () => mockApis(layout()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("3")).toBeInTheDocument());
    await expect(canvas.getByText("Projects")).toBeInTheDocument();
    await expect(api.post).toHaveBeenCalledTimes(1);
    await expect(api.post).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/dashboards/overview/metrics`, { metrics: [{ id: "projects", metric: "org_project_count", params: {}, scope: "this" }] },
    );
    await expect(canvas.queryByRole("button", { name: "Customise" })).not.toBeInTheDocument();
  },
};

/** Only a person who may change the page is offered Customise. */
export const ManagerIsOfferedCustomise: Story = {
  beforeEach: () => mockApis(layout({ can_manage: true })),
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("button", { name: "Customise" })).toBeInTheDocument();
  },
};

/** A page with no widgets says so. */
export const EmptyPageSaysSo: Story = {
  beforeEach: () => mockApis(layout({}, [])),
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("This dashboard has no widgets yet.")).toBeInTheDocument();
  },
};

/** A page that does not exist, or that the person may not see (the server answers 404 for both), reads as not found. */
export const NotFoundPage: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new ApiError(404, "Dashboard not found."));
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("This dashboard was not found.")).toBeInTheDocument();
  },
};

/** Figures scoped to what the person can open say so under the grid. */
export const ScopedFiguresAreNoted: Story = {
  args: { scopedFigures: true },
  beforeEach: () => mockApis(layout()),
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText(/scoped to what you can see/)).toBeInTheDocument();
    await userEvent.tab();
  },
};
