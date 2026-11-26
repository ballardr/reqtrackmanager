import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api, ApiError } from "../../api/client";
import { expectStressStable, stressText } from "../../testing/stressFixtures";
import { TextStress } from "../../testing/TextStress";
import { buildUser, withRouter, withStatefulAuth, withToast } from "../../testing/storybook-helpers";
import { GovernanceHealthPage } from "./GovernanceHealthPage";
import type { Health } from "./types";

const PROJECT_ID = "project-1";
const URL = `/api/v1/projects/${PROJECT_ID}/modules/traceability/health`;
const ROUTE = "/projects/:projectId/modules/traceability/health";

const LIVE: Health = {
  mode: "on_demand", source: "live", computed_at: "2026-11-26T09:00:00Z", stale: false, can_refresh: false,
  categories: [
    { key: "requirement", label: "Requirements", artefact_type: "requirement", kind: "completion", total: 8, done: 5, outstanding: 3, percent: 62 },
    { key: "decision", label: "Decisions", artefact_type: "decision", kind: "completion", total: 4, done: 4, outstanding: 0, percent: 100 },
    { key: "change_request", label: "Change requests", artefact_type: "change_request", kind: "outstanding", total: 6, done: 4, outstanding: 2, percent: null },
  ],
  reviews: [
    { artefact_type: "risk", label: "Risk", due: 3 },
    { artefact_type: "requirement", label: "Requirement", due: 0 },
  ],
  checks: {
    status: "current", run_by: null, run_at: null,
    checks: [
      {
        key: "traceability:required_fields", name: "Required fields",
        types: [
          { artefact_type: "requirement", checked: 8, failing: 2, percent_passing: 75 },
          { artefact_type: "decision", checked: 0, failing: 0, percent_passing: null },
        ],
      },
    ],
  },
};

const SNAPSHOT: Health = {
  ...LIVE, mode: "snapshot_interval", source: "snapshot", computed_at: "2026-11-26T03:30:00Z", stale: true, can_refresh: true,
  checks: { ...LIVE.checks, status: "carried_forward", run_by: { id: "user-1", name: "Alex Morgan" }, run_at: "2026-11-25T20:00:00Z" },
};

const meta: Meta<typeof GovernanceHealthPage> = {
  title: "Modules/Governance/GovernanceHealthPage",
  component: GovernanceHealthPage,
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} })), withToast(), withRouter(`/projects/${PROJECT_ID}/modules/traceability/health`, ROUTE)],
};
export default meta;

type Story = StoryObj<typeof GovernanceHealthPage>;

/** Live figures: categories with progress, reviews due and the check results. */
export const Live: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(LIVE);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("heading", { level: 1, name: "Governance health" })).toBeInTheDocument();
    for (const name of ["Categories", "Reviews due", "Baseline checks"]) {
      await expect(canvas.getByRole("heading", { level: 2, name })).toBeInTheDocument();
    }
    await expect(canvas.getByText("Live figures, read when this page opened.")).toBeInTheDocument();
    const categories = canvas.getByRole("table", { name: "Progress by record category" });
    await expect(within(categories).getByText("62% (5 of 8)")).toBeInTheDocument();
    await expect(within(categories).getByText("2 outstanding")).toBeInTheDocument();
    await expect(within(canvas.getByRole("table", { name: "Reviews due by record type" })).getByText("Risk")).toBeInTheDocument();
    const checks = canvas.getByRole("table", { name: "Baseline check results" });
    await expect(within(checks).getByText("2 of 8")).toBeInTheDocument();
    await expect(within(checks).getByText("75%")).toBeInTheDocument();
    await expect(within(checks).getByText("No records")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Refresh now" })).toBeNull();
  },
};

/** A header click orders the categories by that column. */
export const SortsCategories: Story = {
  ...Live,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Progress by record category" });
    await userEvent.click(within(table).getByRole("button", { name: "Category" }));
    const first = within(table).getAllByRole("row")[1];
    await expect(within(first).getByText("Change requests")).toBeInTheDocument();
  },
};

/** A snapshot states when it was taken, flags that it is stale and names who ran the checks. */
export const StaleSnapshot: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(SNAPSHOT);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText(/^Snapshot taken /)).toBeInTheDocument();
    await expect(canvas.getByText("Stale")).toBeInTheDocument();
    await expect(canvas.getByText("Snapshot at an interval")).toBeInTheDocument();
    await expect(canvas.getByText(/Status: Carried forward from the last run\. Run by Alex Morgan on/)).toBeInTheDocument();
  },
};

/** Refresh now replaces the figures with the server's new snapshot and confirms with a toast. */
export const RefreshesTheSnapshot: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(SNAPSHOT);
    spyOn(api, "post").mockResolvedValue({
      ...SNAPSHOT, stale: false,
      categories: [{ key: "requirement", label: "Requirements", artefact_type: "requirement", kind: "completion", total: 8, done: 8, outstanding: 0, percent: 100 }],
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Refresh now" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${URL}/refresh`));
    await expect(await canvas.findByText("100% (8 of 8)")).toBeInTheDocument();
    await expect(canvas.queryByText("Stale")).toBeNull();
    await expect(await within(document.body).findByText("Governance health refreshed.")).toBeInTheDocument();
  },
};

/** A refused refresh shows the server's message and keeps the figures. */
export const RefreshFailureShowsAnError: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(SNAPSHOT);
    spyOn(api, "post").mockRejectedValue(new Error("A refresh of this project's governance health is already running."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Refresh now" }));
    await expect(await within(document.body).findByText("A refresh of this project's governance health is already running.")).toBeInTheDocument();
    await expect(canvas.getByRole("table", { name: "Progress by record category" })).toBeInTheDocument();
  },
};

/** With no baseline check enabled only the status line shows. */
export const ChecksNotEnabled: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ ...LIVE, checks: { status: "not_enabled", run_by: null, run_at: null, checks: [] } });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("No baseline checks are enabled.")).toBeInTheDocument();
    await expect(canvas.queryByRole("table", { name: "Baseline check results" })).toBeNull();
  },
};

/** A viewer who may read none of the governed record types sees an empty state in each section. */
export const EmptyCategories: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ ...LIVE, categories: [], reviews: [] });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getAllByText("No governance figures are available for the record types you can view.").length).toBeGreaterThanOrEqual(2));
  },
};

/** A project that has no governance health shows a not-found message. */
export const NotFound: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new ApiError(404, "Not found"));
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("Governance health is not available for this project.")).toBeInTheDocument();
  },
};

/** Any other failed read offers Retry. */
export const LoadFailure: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new Error("down"));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Governance health could not be loaded.")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...Live, globals: { theme: "dark" } };

/** Long record type names keep every table's columns aligned. The first mounted page reads the short data, the second the long. */
export const LongText: Story = {
  beforeEach: () => {
    let reads = 0;
    spyOn(api, "get").mockImplementation(async () => {
      const long = reads++ > 0;
      return {
        ...LIVE,
        categories: LIVE.categories.map((c, index) => ({ ...c, label: index === 0 ? stressText(long, c.label) : c.label })),
        reviews: LIVE.reviews.map((r, index) => ({ ...r, label: index === 0 ? stressText(long, r.label, "word") : r.label })),
        checks: {
          ...LIVE.checks,
          checks: LIVE.checks.checks.map((check) => ({ ...check, name: stressText(long, check.name) })),
        },
      };
    });
  },
  render: () => <TextStress render={() => <GovernanceHealthPage />} />,
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getAllByRole("table", { name: "Baseline check results" })).toHaveLength(2));
    await expectStressStable(canvasElement);
  },
};
