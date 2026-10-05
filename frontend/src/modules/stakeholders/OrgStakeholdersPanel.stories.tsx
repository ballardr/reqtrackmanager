import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { buildStakeholder, buildStakeholderScheme } from "./fixtures";
import { OrgStakeholdersPanel } from "./OrgStakeholdersPanel";
import type { PersonaTypeDefinition, Stakeholder } from "./types";

const ORG_ID = "org-1";
const BASE = `/api/v1/orgs/${ORG_ID}/modules/stakeholders`;

const TYPES: PersonaTypeDefinition[] = [
  { id: "stype-regulator", organization_id: ORG_ID, name: "Regulator", sort_order: 0, is_active: true },
  { id: "stype-off", organization_id: ORG_ID, name: "Inactive type", sort_order: 1, is_active: false },
];

function orgStakeholder(overrides: Partial<Stakeholder> = {}): Stakeholder {
  return buildStakeholder({ scope: "organization", organization_id: ORG_ID, project_id: null, ...overrides });
}

function mockPanelApis(stakeholders: Stakeholder[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.startsWith(`${BASE}/stakeholders`)) return stakeholders;
    if (path === `${BASE}/stakeholder-types`) return TYPES;
    if (path === `/api/v1/orgs/${ORG_ID}/scoring-schemes/stakeholder`) return buildStakeholderScheme();
    if (path === `/api/v1/orgs/${ORG_ID}/users`) return [];
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof OrgStakeholdersPanel> = {
  title: "Modules/Stakeholders/OrgStakeholdersPanel",
  component: OrgStakeholdersPanel,
  args: { orgId: ORG_ID },
  decorators: [withRouter("/org-overview"), withToast()],
};
export default meta;

type Story = StoryObj<typeof OrgStakeholdersPanel>;

export const ListsOrgStakeholdersWithoutScopeColumn: Story = {
  beforeEach: () => mockPanelApis([orgStakeholder()]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Pat Regulator")).toBeInTheDocument());
    await expect(canvas.getByRole("columnheader", { name: "Cadence" })).toBeInTheDocument();
    await expect(canvas.queryByRole("columnheader", { name: "Scope" })).not.toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockPanelApis([]),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("No organisation-scoped Stakeholders recorded yet.")).toBeInTheDocument());
  },
};

export const CreateOffersOnlyActiveOrgTypes: Story = {
  beforeEach: () => mockPanelApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New Stakeholder" }));
    await userEvent.click(canvas.getByRole("button", { name: "New Stakeholder" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await expect(dialog.getByRole("option", { name: "Regulator" })).toBeInTheDocument();
    await expect(dialog.queryByRole("option", { name: "Inactive type" })).not.toBeInTheDocument();
  },
};

export const CreateStakeholder: Story = {
  beforeEach: () => {
    mockPanelApis([]);
    spyOn(api, "post").mockResolvedValue(orgStakeholder());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New Stakeholder" }));
    await userEvent.click(canvas.getByRole("button", { name: "New Stakeholder" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "New Stakeholder (organisation)" }));
    await userEvent.type(dialog.getByLabelText("Stakeholder name"), "Pat Regulator");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`${BASE}/stakeholders`, expect.objectContaining({ name: "Pat Regulator" })),
    );
  },
};

export const DarkTheme: Story = { ...ListsOrgStakeholdersWithoutScopeColumn, globals: { theme: "dark" } };
