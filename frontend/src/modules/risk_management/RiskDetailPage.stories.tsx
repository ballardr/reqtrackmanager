import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildGraph, buildGraphNode } from "../../testing/artefactLinksFixtures";
import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { buildReview, buildRisk, buildRiskScheme, buildTreatment, ORG_USERS, PROJECT_ID, RISK_ID, RISK_TYPES } from "./riskFixtures";
import { RiskDetailPage } from "./RiskDetailPage";
import type { Risk, RiskVersion } from "./types";

const BASE = `/api/v1/projects/${PROJECT_ID}/modules/risk_management/risks/${RISK_ID}`;

const LINKED = buildGraphNode({ type: "requirement", id: "req-1", type_label: "Requirement", label: "REQ-001 Dual-source the firmware", status: null });

function version(n: number, overrides: Partial<RiskVersion> = {}): RiskVersion {
  return {
    id: `v${n}`, risk_id: RISK_ID, version_number: n, valid_from: `2026-01-1${n}T09:00:00Z`, valid_to: null,
    title: "Supplier firmware may be late", statement: "", cause: "", risk_event: "", consequence: "", project_type_id: "rt-2",
    treatment_strategy: "mitigate", acceptance_criteria: "",
    inherent_likelihood_level_id: "lik-4", inherent_consequence_level_id: "con-4", inherent_detectability_level_id: null,
    residual_likelihood_level_id: null, residual_consequence_level_id: null, residual_detectability_level_id: null,
    status: "assessed", owner_id: "user-1", review_date: null, change_note: "", created_by: "user-1", created_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

function mockApis(current: Risk) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === BASE) return current;
    if (path.endsWith("/versions")) return [version(1, { status: "identified", change_note: "Initial" }), version(2)];
    if (path.endsWith("/treatments")) return { items: [buildTreatment()], hidden_count: 0, effective_count: 0, needs_reassessment_count: 0 };
    if (path.endsWith("/reviews")) return [buildReview()];
    if (path.includes("/scoring-schemes/risk")) return buildRiskScheme();
    if (path.includes("/risk-types")) return RISK_TYPES;
    if (path.endsWith("/comments") || path.endsWith("/files")) return [];
    if (path.includes(`/artefacts/risk/${RISK_ID}/link-graph`)) return buildGraph([[LINKED]]);
    if (path.includes("/users")) return ORG_USERS;
    if (path.endsWith(`/projects/${PROJECT_ID}`)) return { id: PROJECT_ID, organization_id: "org-1" };
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof RiskDetailPage> = {
  title: "Modules/RiskManagement/RiskDetailPage",
  component: RiskDetailPage,
  decorators: [
    withAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" })),
    withRouter(`/projects/${PROJECT_ID}/modules/risk_management/risks/${RISK_ID}`, "/projects/:projectId/modules/risk_management/risks/:riskId"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof RiskDetailPage>;

export const ShowsFieldsRatingsTreatmentsReviewsAndHistory: Story = {
  beforeEach: () => mockApis(buildRisk()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Supplier firmware may be late" })).toBeInTheDocument());
    await expect(canvas.getByText("RSK-001")).toBeInTheDocument();
    await expect(canvas.getAllByText("Assessed").length).toBeGreaterThan(0);
    await expect(canvas.getAllByText("Likely × Major").length).toBeGreaterThan(0);
    await expect(canvas.getByText("No effective treatment")).toBeInTheDocument();
    await expect(await canvas.findByRole("table", { name: "Treatment links" })).toBeInTheDocument();
    await expect(await canvas.findByText("Supplier confirmed the date.")).toBeInTheDocument();
    await expect(await canvas.findByRole("heading", { name: "Version history" })).toBeInTheDocument();
    // Once in the treatments table, once in the Links panel.
    await waitFor(() => expect(canvas.getAllByRole("link", { name: "REQ-001 Dual-source the firmware" })).toHaveLength(2));
    await expect(canvas.getByText("Risk matrix: inherent and residual rating")).toBeInTheDocument();
  },
};

export const OverdueAndArchivedAreFlagged: Story = {
  beforeEach: () => mockApis(buildRisk({ is_review_overdue: true, is_archived: true })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Review overdue")).toHaveClass("badge--danger"));
    await expect(canvas.getByText("Archived")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Unarchive" })).toBeInTheDocument();
  },
};

export const ChangeStatusPostsTheTransition: Story = {
  beforeEach: () => {
    mockApis(buildRisk());
    spyOn(api, "post").mockResolvedValue(buildRisk({ status: "treatment_planned", allowed_next_statuses: ["treatment_in_progress"] }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Change status" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Change status of RSK-001" }));
    await userEvent.selectOptions(dialog.getByLabelText("New status"), "treatment_planned");
    await userEvent.click(dialog.getByRole("button", { name: "Change status" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${BASE}/transition`, { status: "treatment_planned", comment: "" }));
    await waitFor(() => expect(canvas.getAllByText("Treatment planned").length).toBeGreaterThan(0));
  },
};

/** Only the changed fields are sent, with the change note; an edit that changes nothing sends nothing. */
export const EditSendsOnlyChangedFields: Story = {
  beforeEach: () => {
    mockApis(buildRisk());
    spyOn(api, "put").mockResolvedValue(buildRisk({ title: "Supplier firmware will be late", version_number: 3 }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Edit" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Edit RSK-001" }));
    const title = dialog.getByLabelText("Risk title");
    await userEvent.clear(title);
    await userEvent.type(title, "Supplier firmware will be late");
    await userEvent.type(dialog.getByLabelText("Change note"), "Wording");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(BASE, { title: "Supplier firmware will be late", change_note: "Wording" }));
  },
};

export const EditWithNoChangeSendsNothing: Story = {
  beforeEach: () => {
    mockApis(buildRisk());
    spyOn(api, "put").mockResolvedValue(buildRisk());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Edit" }));
    await userEvent.click(within(within(document.body).getByRole("dialog")).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(canvas.queryByRole("dialog")).not.toBeInTheDocument());
    await expect(api.put).not.toHaveBeenCalled();
  },
};

export const MissingRiskShowsAnError: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith(`/projects/${PROJECT_ID}`)) return { id: PROJECT_ID, organization_id: "org-1" };
      if (path.includes("/users")) return ORG_USERS;
      if (path.includes("/risk-types")) return RISK_TYPES;
      if (path.includes("/scoring-schemes")) return buildRiskScheme();
      throw new Error("not found");
    });
  },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText(/could not be found|not found/i)).toBeInTheDocument());
  },
};

export const DarkTheme: Story = { ...ShowsFieldsRatingsTreatmentsReviewsAndHistory, globals: { theme: "dark" } };
