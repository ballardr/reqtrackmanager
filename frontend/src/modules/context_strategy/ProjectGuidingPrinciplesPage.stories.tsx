import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildProject, withRouter, withToast } from "../../testing/storybook-helpers";
import { ProjectGuidingPrinciplesPage } from "./ProjectGuidingPrinciplesPage";
import type { GuidingPrinciple } from "./types";

const PROJECT_ID = "project-1";

function guidingPrinciple(overrides: Partial<GuidingPrinciple> = {}): GuidingPrinciple {
  return {
    id: "gp-1", scope: "project", organization_id: null, project_id: PROJECT_ID, creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null, name: "Field data is captured once",
    principle_statement: "Every field observation is recorded exactly once, at the point of inspection.",
    rationale: "", priority: "high", status: "active", owner_id: null, version_number: 3, is_locked: true,
    created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

function mockPageApis(guidingPrinciples: GuidingPrinciple[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/projects/${PROJECT_ID}`) return buildProject({ id: PROJECT_ID, organization_id: "org-1" });
    if (path.startsWith(`/api/v1/projects/${PROJECT_ID}/modules/context_strategy/guiding-principles`)) return guidingPrinciples;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof ProjectGuidingPrinciplesPage> = {
  title: "Modules/ContextStrategy/ProjectGuidingPrinciplesPage",
  component: ProjectGuidingPrinciplesPage,
  decorators: [
    withRouter(`/projects/${PROJECT_ID}/modules/context_strategy/guiding-principles`, "/projects/:projectId/modules/context_strategy/guiding-principles"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectGuidingPrinciplesPage>;

export const ListsGuidingPrinciples: Story = {
  beforeEach: () => mockPageApis([guidingPrinciple(), guidingPrinciple({ id: "gp-2", name: "Operate safely under degraded connectivity", status: "draft" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Field data is captured once")).toBeInTheDocument());
    await expect(canvas.getByText("Operate safely under degraded connectivity")).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockPageApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No Guiding Principle recorded for this project yet.")).toBeInTheDocument());
  },
};

export const OpenCreateModal: Story = {
  beforeEach: () => mockPageApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New Guiding Principle" }));
    await userEvent.click(canvas.getByRole("button", { name: "New Guiding Principle" }));
    // `GuidingPrincipleFormModal` portals to `document.body`.
    await expect(within(document.body).getByRole("heading", { name: "New Guiding Principle (project)" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ListsGuidingPrinciples };
export const DarkTheme: Story = { ...ListsGuidingPrinciples, globals: { theme: "dark" } };
