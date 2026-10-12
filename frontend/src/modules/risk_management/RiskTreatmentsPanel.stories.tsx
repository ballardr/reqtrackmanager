import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../../api/client";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { buildTreatment, PROJECT_ID, RISK_ID } from "./riskFixtures";
import { RiskTreatmentsPanel } from "./RiskTreatmentsPanel";
import type { RiskTreatmentList } from "./types";

const URL_BASE = `/api/v1/projects/${PROJECT_ID}/modules/risk_management/risks/${RISK_ID}/treatments`;

function list(items: RiskTreatmentList["items"], overrides: Partial<RiskTreatmentList> = {}): RiskTreatmentList {
  return {
    items, hidden_count: 0, needs_reassessment_count: 0,
    effective_count: items.filter((t) => t.status === "effective").length, ...overrides,
  };
}

const meta: Meta<typeof RiskTreatmentsPanel> = {
  title: "Modules/RiskManagement/RiskTreatmentsPanel",
  component: RiskTreatmentsPanel,
  args: { projectId: PROJECT_ID, riskId: RISK_ID, onChanged: fn() },
  decorators: [withRouter("/"), withToast()],
};
export default meta;

type Story = StoryObj<typeof RiskTreatmentsPanel>;

/** A link alone only proposes a treatment; the page says so and nothing counts as effective. */
export const ProposedLinksAreNotYetEffective: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(list([buildTreatment()]));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Proposed")).toHaveClass("badge--muted"));
    await expect(canvas.getByText(/No effective treatment yet/)).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "REQ-001 Dual-source the firmware" })).toHaveAttribute("href", `/projects/${PROJECT_ID}/requirements/req-1`);
  },
};

export const NeedsReassessmentShowsWhy: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(
      list(
        [buildTreatment({ status: "needs_reassessment", rationale: "Passed the audit.", reassessment_reason: "REQ-001 was edited after this verdict." })],
        { needs_reassessment_count: 1 },
      ),
    );
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Needs reassessment")).toHaveClass("badge--warning"));
    await expect(canvas.getByText("REQ-001 was edited after this verdict.")).toBeInTheDocument();
    await expect(canvas.getByText(/1 needs reassessment/)).toBeInTheDocument();
  },
};

export const EffectiveCountsAndHiddenLinksAreCounted: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(list([buildTreatment({ status: "effective", rationale: "Reviewed by the owner." })], { hidden_count: 2 }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("1 effective treatment.")).toBeInTheDocument());
    await expect(canvas.getByText(/2 further treatment links point to records you cannot view/)).toBeInTheDocument();
  },
};

export const AssessingSendsTheVerdictAndRationale: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(list([buildTreatment()]));
    spyOn(api, "put").mockResolvedValue(buildTreatment({ status: "effective", rationale: "Tested on the rig." }));
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Assess REQ-001 Dual-source the firmware" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await userEvent.type(dialog.getByLabelText("Rationale"), "Tested on the rig.");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${URL_BASE}/link-1`, { status: "effective", rationale: "Tested on the rig." }));
    await waitFor(() => expect(args.onChanged).toHaveBeenCalled());
  },
};

/** The backend's rule (a rationale for Effective/Ineffective) shows in the dialog, which stays open. */
export const MissingRationaleIsShownInTheDialog: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(list([buildTreatment()]));
    spyOn(api, "put").mockRejectedValue(new ApiError(409, "A rationale is required to mark a treatment effective."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: /^Assess/ }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await expect(await dialog.findByText("A rationale is required to mark a treatment effective.")).toBeInTheDocument();
  },
};

export const EmptyExplainsHowToAddTreatments: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(list([]));
  },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText(/Link a requirement, design or action in the Links panel/)).toBeInTheDocument());
  },
};

export const DarkTheme: Story = { ...ProposedLinksAreNotYetEffective, globals: { theme: "dark" } };
