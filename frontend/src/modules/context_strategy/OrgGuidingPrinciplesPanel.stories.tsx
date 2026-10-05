import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { OrgGuidingPrinciplesPanel } from "./OrgGuidingPrinciplesPanel";
import type { GuidingPrinciple } from "./types";

const ORG_ID = "org-1";

function guidingPrinciple(overrides: Partial<GuidingPrinciple> = {}): GuidingPrinciple {
  return {
    id: "gp-1", scope: "organization", organization_id: ORG_ID, project_id: null, creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null, name: "Operate safely under degraded connectivity",
    principle_statement: "Field operations must degrade gracefully, never silently, when connectivity is lost.",
    rationale: "", priority: "high", status: "active", owner_id: null, version_number: 3, is_locked: true,
    created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

function mockPanelApis(guidingPrinciples: GuidingPrinciple[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.startsWith(`/api/v1/orgs/${ORG_ID}/modules/context_strategy/guiding-principles`)) return guidingPrinciples;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof OrgGuidingPrinciplesPanel> = {
  title: "Modules/ContextStrategy/OrgGuidingPrinciplesPanel",
  component: OrgGuidingPrinciplesPanel,
  args: { orgId: ORG_ID },
  decorators: [withRouter("/org-overview"), withToast()],
};
export default meta;

type Story = StoryObj<typeof OrgGuidingPrinciplesPanel>;

export const ListsOrgGuidingPrinciples: Story = {
  beforeEach: () => mockPanelApis([guidingPrinciple(), guidingPrinciple({ id: "gp-2", name: "Field data is captured once", status: "draft" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Operate safely under degraded connectivity")).toBeInTheDocument());
    await expect(canvas.getByText("Field data is captured once")).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockPanelApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No organisation-scoped Guiding Principle recorded yet.")).toBeInTheDocument());
  },
};

export const OpenCreateModal: Story = {
  beforeEach: () => mockPanelApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New Guiding Principle" }));
    await userEvent.click(canvas.getByRole("button", { name: "New Guiding Principle" }));
    await expect(within(document.body).getByRole("heading", { name: "New Guiding Principle (organisation)" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ListsOrgGuidingPrinciples };
export const DarkTheme: Story = { ...ListsOrgGuidingPrinciples, globals: { theme: "dark" } };
