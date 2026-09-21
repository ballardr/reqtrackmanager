import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildProject, buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { ProjectDecisionsPage } from "./ProjectDecisionsPage";
import type { Decision, DecisionTypeDefinition } from "./types";

const PROJECT_ID = "project-1";

const DECISION_TYPES: DecisionTypeDefinition[] = [
  { id: "dt-1", project_id: PROJECT_ID, name: "Architecture", sort_order: 0 },
  { id: "dt-2", project_id: PROJECT_ID, name: "Strategy", sort_order: 1 },
];

function decision(overrides: Partial<Decision> = {}): Decision {
  return {
    id: "decision-1", project_id: PROJECT_ID, unique_code: "DEC-001", title: "Adopt PostgreSQL for the new service",
    decision_statement: "Use PostgreSQL as the backing store.", decision_type_id: "dt-1", status: "approved",
    decision_date: "2026-02-01", decision_maker_id: "user-1", owner_id: "user-1", context: null,
    options_considered: null, chosen_option: null, rationale: null, consequences: null, assumptions: null,
    constraints: null, creator_id: "user-1", is_archived: false, archived_at: null, archived_by: null,
    is_locked: true, created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

function mockPageApis(decisions: Decision[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/projects/${PROJECT_ID}`) return buildProject({ id: PROJECT_ID, organization_id: "org-1" });
    if (path.includes("/orgs/org-1/users")) return [];
    if (path.includes("/templates")) return [];
    if (path.includes("/decision-types")) return DECISION_TYPES;
    if (path.startsWith(`/api/v1/projects/${PROJECT_ID}/modules/decisions?`) || path.endsWith("/modules/decisions")) return decisions;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof ProjectDecisionsPage> = {
  title: "Modules/Decisions/ProjectDecisionsPage",
  component: ProjectDecisionsPage,
  decorators: [
    withRouter(`/projects/${PROJECT_ID}/modules/decisions`, "/projects/:projectId/modules/decisions"),
    withToast(),
    withAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" })),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectDecisionsPage>;

export const ListsDecisions: Story = {
  beforeEach: () => mockPageApis([decision(), decision({ id: "decision-2", unique_code: "DEC-002", title: "Use Terraform for infra", status: "draft", is_locked: false })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Adopt PostgreSQL for the new service")).toBeInTheDocument());
    await expect(canvas.getByText("Use Terraform for infra")).toBeInTheDocument();
    await expect(canvas.getByText("DEC-001")).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockPageApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No Decisions recorded for this project yet.")).toBeInTheDocument());
  },
};

export const SwitchToDecisionTypesTab: Story = {
  beforeEach: () => mockPageApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("tab", { name: "Decision Types" }));
    await userEvent.click(canvas.getByRole("tab", { name: "Decision Types" }));
    await expect(canvas.getByDisplayValue("Architecture")).toBeInTheDocument();
  },
};

export const OpenCreateModal: Story = {
  beforeEach: () => mockPageApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New decision" }));
    await userEvent.click(canvas.getByRole("button", { name: "New decision" }));
    // `DecisionFormModal` portals to `document.body` — see that file's own
    // stories for why this query isn't `within(canvasElement)`.
    await expect(within(document.body).getByRole("heading", { name: "New decision" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ListsDecisions };
export const DarkTheme: Story = { ...ListsDecisions, globals: { theme: "dark" } };
