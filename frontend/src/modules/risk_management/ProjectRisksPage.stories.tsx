import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { buildRisk, buildRiskScheme, ORG_USERS, PROJECT_ID, RISK_TYPES } from "./riskFixtures";
import { ProjectRisksPage } from "./ProjectRisksPage";
import type { Risk } from "./types";

const RISKS: Risk[] = [
  buildRisk(),
  buildRisk({
    id: "risk-2", unique_code: "RSK-002", title: "Test rig unavailable", status: "mitigated", risk_type_id: "rt-1", risk_type_name: "Safety",
    inherent_likelihood_level_id: "lik-1", inherent_consequence_level_id: "con-5",
    inherent_rating: { scoring_model_key: "lxc", raw: 5, normalised: 0.2, label: "High", tone: "warning" },
    residual_likelihood_level_id: "lik-1", residual_consequence_level_id: "con-2",
    residual_rating: { scoring_model_key: "lxc", raw: 2, normalised: 0.08, label: "Low", tone: "muted" },
    is_effectively_treated: true, effective_treatment_count: 1, owner: { type: "org_group", id: "group-1", label: "Safety Board", member_count: 2, exists: true }, review_date: "2020-01-01", is_review_overdue: true,
  }),
];

function mockApis(risks: Risk[] = RISKS) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/scoring-schemes/risk")) return buildRiskScheme();
    if (path.includes("/risk-types")) return RISK_TYPES;
    if (path.split("?")[0].endsWith("/modules/risk_management/risks")) return risks;
    if (path.includes("/users")) return ORG_USERS;
    if (path.endsWith("/groups")) return [];
    if (path.endsWith(`/projects/${PROJECT_ID}`)) return { id: PROJECT_ID, organization_id: "org-1" };
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof ProjectRisksPage> = {
  title: "Modules/RiskManagement/ProjectRisksPage",
  component: ProjectRisksPage,
  decorators: [
    withAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" })),
    withRouter(`/projects/${PROJECT_ID}/modules/risk_management/risks`, "/projects/:projectId/modules/risk_management/risks"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectRisksPage>;

export const RegisterShowsRatingsStatusOwnerAndOverdue: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Risks" });
    const row = within(within(table).getByRole("link", { name: "RSK-002" }).closest("tr")!);
    await expect(row.getByText("Test rig unavailable")).toBeInTheDocument();
    await expect(row.getByText("High")).toHaveClass("badge--warning");
    await expect(row.getByText("Low")).toHaveClass("badge--muted");
    await expect(row.getByText("Mitigated")).toBeInTheDocument();
    await expect(row.getByText("Safety Board")).toBeInTheDocument();
    await expect(row.getByText("Org group · 2 members")).toBeInTheDocument();
    await expect(row.getByText("Overdue")).toBeInTheDocument();
    await expect(within(table).getByRole("link", { name: "RSK-001" })).toHaveAttribute(
      "href", `/projects/${PROJECT_ID}/modules/risk_management/risks/risk-1`,
    );
  },
};

export const EmptyProjectSaysSo: Story = {
  beforeEach: () => mockApis([]),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("No Risks recorded for this project yet.")).toBeInTheDocument());
  },
};

export const StatusFilterUsesLabels: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Risks" });
    await userEvent.selectOptions(canvas.getByLabelText("Status"), "mitigated");
    await waitFor(() => expect(canvas.queryByRole("link", { name: "RSK-001" })).not.toBeInTheDocument());
    await expect(canvas.getByRole("link", { name: "RSK-002" })).toBeInTheDocument();
  },
};

export const OverdueFilterNarrowsTheRegister: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Risks" });
    await userEvent.click(canvas.getByLabelText("Review overdue"));
    await waitFor(() => expect(canvas.queryByRole("link", { name: "RSK-001" })).not.toBeInTheDocument());
    await expect(canvas.getByRole("link", { name: "RSK-002" })).toBeInTheDocument();
  },
};

export const NoEffectiveTreatmentFilter: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Risks" });
    await userEvent.click(canvas.getByLabelText("No effective treatment"));
    await waitFor(() => expect(canvas.queryByRole("link", { name: "RSK-002" })).not.toBeInTheDocument());
    await expect(canvas.getByRole("link", { name: "RSK-001" })).toBeInTheDocument();
  },
};

/** Clicking a matrix cell returns to the register narrowed to that cell, with a chip naming it. */
export const MatrixCellNarrowsTheRegister: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Risks" });
    await userEvent.click(canvas.getByRole("tab", { name: "Matrix" }));
    await userEvent.click(await canvas.findByRole("button", { name: /Likelihood Likely, Consequence Major: High, 1 item/ }));
    await expect(await canvas.findByText(/Inherent: Likely likelihood, Major consequence/)).toBeInTheDocument();
    await expect(canvas.queryByRole("link", { name: "RSK-002" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Clear matrix filter" }));
    await expect(await canvas.findByRole("link", { name: "RSK-002" })).toBeInTheDocument();
  },
};

/** Widened to a parent project, the matrix plots that project's risks too (levels are organisation-wide),
 * so a product's risk can be read across the sub-projects that make it up. */
export const MatrixPlotsRisksOfRelatedProjects: Story = {
  decorators: [withAuth(buildUser({ id: "user-1", ui_preferences: { default_project_scope: "parents" } }))],
  beforeEach: () => {
    const foreign = buildRisk({
      id: "risk-9", unique_code: "RSK-009", title: "Parent project risk",
      from_project_id: "project-parent", from_project_name: "Platform", from_project_code: "PLAT",
    });
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/scope-options")) return { has_parents: true, has_children: false, truncated: false };
      if (path.includes("/scoring-schemes/risk")) return buildRiskScheme();
      if (path.includes("/risk-types")) return RISK_TYPES;
      if (path.split("?")[0].endsWith("/modules/risk_management/risks")) return path.includes("project_scope=parents") ? [...RISKS, foreign] : RISKS;
      if (path.includes("/users")) return ORG_USERS;
      if (path.endsWith("/groups")) return [];
      if (path.endsWith(`/projects/${PROJECT_ID}`)) return { id: PROJECT_ID, organization_id: "org-1" };
      throw new Error(`Unmocked GET: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Risks" });
    await expect(within(table).getByText("From Platform")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("tab", { name: "Matrix" }));
    await expect(await canvas.findByRole("button", { name: /Likelihood Likely, Consequence Major: High, 2 items/ })).toBeInTheDocument();
  },
};

export const NewRiskPostsTheForm: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "post").mockResolvedValue(buildRisk({ id: "risk-3" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "New risk" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "New risk" }));
    await userEvent.type(dialog.getByLabelText("Risk title"), "Vendor lock-in");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/modules/risk_management/risks`,
        expect.objectContaining({ title: "Vendor lock-in", owner: { type: "user", id: "user-1" } }),
      ),
    );
  },
};

export const DarkTheme: Story = { ...RegisterShowsRatingsStatusOwnerAndOverdue, globals: { theme: "dark" } };
