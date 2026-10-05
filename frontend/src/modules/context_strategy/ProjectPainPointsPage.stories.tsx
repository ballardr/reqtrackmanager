import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildProject, withRouter, withToast } from "../../testing/storybook-helpers";
import { ProjectPainPointsPage } from "./ProjectPainPointsPage";
import type { EffectivePainPointType, PainPoint } from "./types";

const PROJECT_ID = "project-1";

const TYPES: EffectivePainPointType[] = [
  { id: "type-operator", name: "Operator", display_order: 0, is_enabled: true, source: "org" },
];

function painPoint(overrides: Partial<PainPoint> = {}): PainPoint {
  return {
    id: "pain-point-1", project_id: PROJECT_ID, pain_point_type_id: "type-operator", pain_point_type_name: "Operator",
    creator_id: "user-1", is_archived: false, archived_at: null, archived_by: null,
    title: "Report delays under poor connectivity", description: "Field reports queue for days.",
    source: "Operator interviews", impact: "Decisions are made on stale data.", evidence: "12 reports last month.",
    priority: "high", status: "submitted", owner_id: null, date_identified: "2026-01-05", is_locked: false,
    created_at: "2026-01-05T09:00:00Z", updated_at: "2026-01-05T09:00:00Z",
    ...overrides,
  };
}

function mockPageApis(painPoints: PainPoint[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/projects/${PROJECT_ID}`) return buildProject({ id: PROJECT_ID, organization_id: "org-1" });
    if (path.startsWith(`/api/v1/projects/${PROJECT_ID}/modules/context_strategy/pain-point-types`)) return TYPES;
    if (path.startsWith(`/api/v1/projects/${PROJECT_ID}/modules/context_strategy/pain-points`)) return painPoints;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof ProjectPainPointsPage> = {
  title: "Modules/ContextStrategy/ProjectPainPointsPage",
  component: ProjectPainPointsPage,
  decorators: [
    withRouter(`/projects/${PROJECT_ID}/modules/context_strategy/pain-points`, "/projects/:projectId/modules/context_strategy/pain-points"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectPainPointsPage>;

export const ListsPainPoints: Story = {
  beforeEach: () => mockPageApis([painPoint(), painPoint({ id: "pain-point-2", title: "Competitive pricing pressure", status: "rejected" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Report delays under poor connectivity")).toBeInTheDocument());
    await expect(canvas.getByText("Competitive pricing pressure")).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockPageApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No Pain Points recorded for this project yet.")).toBeInTheDocument());
  },
};

export const OpenCreateModal: Story = {
  beforeEach: () => mockPageApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New Pain Point" }));
    await userEvent.click(canvas.getByRole("button", { name: "New Pain Point" }));
    // `PainPointFormModal` portals to `document.body`.
    await expect(within(document.body).getByRole("heading", { name: "New Pain Point" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ListsPainPoints };
export const DarkTheme: Story = { ...ListsPainPoints, globals: { theme: "dark" } };
