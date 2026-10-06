import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildScoringScheme, withRouter } from "../../testing/storybook-helpers";
import { PainPointPrioritisationReportView } from "./PainPointPrioritisationReportView";
import { prioritisationEntry, prioritisationResult } from "./reportFixtures";

const meta: Meta<typeof PainPointPrioritisationReportView> = {
  title: "Modules/ContextStrategy/Reports/PainPointPrioritisationReportView",
  component: PainPointPrioritisationReportView,
  decorators: [withRouter("/projects/project-1/reports")],
  args: {
    entry: prioritisationEntry(), result: prioritisationResult(), scope: { kind: "project", id: "project-1" },
    values: {}, onValueChange: fn(),
  },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/scoring-schemes/pain_point")) return buildScoringScheme();
      throw new Error(`Unmocked GET: ${path}`);
    });
  },
};
export default meta;

type Story = StoryObj<typeof PainPointPrioritisationReportView>;

/** The matrix places each scored item at its worst persona's cell and colours cells by band. */
export const MatrixAndRankedList: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", { name: "Severity × Frequency × Confidence" })).toBeInTheDocument();
    await expect(canvas.getByLabelText(/Severity Major, Frequency Constant: Critical, 1 item/)).toBeInTheDocument();
    await expect(canvas.getByLabelText(/Severity Blocker, Frequency Rare: .*, 1 item/)).toBeInTheDocument();
    const rows = within(canvas.getByRole("table", { name: "Ranked Pain Points" })).getAllByRole("row");
    await expect(rows[1]).toHaveTextContent("Report delays under poor connectivity");
    await expect(rows[2]).toHaveTextContent("Checkout times out");
    // Intentional items are not ranked.
    await expect(canvas.queryByText("Premium export limit")).not.toBeInTheDocument();
  },
};

/** A Blocker stays flagged (naming the persona) and churn risk is shown beside the score. */
export const BlockerAndChurnRiskBadges: Story = {
  play: async ({ canvasElement }) => {
    const ranked = within(within(canvasElement).getByRole("table", { name: "Ranked Pain Points" }));
    const row = within(ranked.getByRole("row", { name: /Checkout times out/ }));
    await expect(row.getByText("Blocker")).toHaveAttribute("title", "Unusable for: Field Technician");
    await expect(row.getByText("Churn risk")).toBeInTheDocument();
    await expect(row.getByText("Accepted")).toBeInTheDocument();
  },
};

/** The generic section tables the view does not replace (blockers, persona breakdown) still render once. */
export const KeepsRemainingGenericSections: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("region", { name: "Blockers" })).toBeInTheDocument();
    await expect(canvas.getByRole("region", { name: "Per-persona breakdown" })).toBeInTheDocument();
    await expect(canvas.queryByRole("region", { name: "Severity × Frequency matrix" })).not.toBeInTheDocument();
  },
};

/** The view owns `model_key` and `rollup`: switching either asks the runner to change that value. */
export const SwitchersChangeModelAndRollup: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByLabelText("Scoring model")).toBeInTheDocument());
    await expect(canvas.getByLabelText("Scoring model")).toHaveValue("sxfxc");
    await userEvent.selectOptions(canvas.getByLabelText("Scoring model"), "sxf");
    await expect(args.onValueChange).toHaveBeenCalledWith("model_key", "sxf");
    await userEvent.selectOptions(canvas.getByLabelText("Combine personas by"), "worst_case");
    await expect(args.onValueChange).toHaveBeenCalledWith("rollup", "worst_case");
  },
};

/** At organisation scope the list also names each Pain Point's project. */
export const OrganisationScopeShowsProject: Story = {
  args: { scope: { kind: "organization", id: "org-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === "/api/v1/orgs/org-1/scoring-schemes/pain_point") return buildScoringScheme();
      throw new Error(`Unmocked GET: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("columnheader", { name: "Project" })).toBeInTheDocument();
  },
};

/** Narrowed to one project, the list drops the Project column and the switcher uses that project's own scheme. */
export const OrganisationReportNarrowedToAProject: Story = {
  args: { scope: { kind: "organization", id: "org-1" }, values: { project_id: "project-1" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByLabelText("Scoring model")).toBeInTheDocument());
    await expect(api.get).toHaveBeenCalledWith("/api/v1/projects/project-1/scoring-schemes/pain_point");
    await expect(canvas.queryByRole("columnheader", { name: "Project" })).not.toBeInTheDocument();
  },
};

export const NoScoredItems: Story = {
  args: { result: prioritisationResult({ data: { rollup: "weighted_average", groups: [] } }) },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("table", { name: "Ranked Pain Points" })).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...MatrixAndRankedList, globals: { theme: "light" } };
export const DarkTheme: Story = { ...MatrixAndRankedList, globals: { theme: "dark" } };
