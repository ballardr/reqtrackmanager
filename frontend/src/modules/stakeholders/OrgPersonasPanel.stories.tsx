import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { buildPersona } from "./fixtures";
import { OrgPersonasPanel } from "./OrgPersonasPanel";
import type { Persona, PersonaTypeDefinition } from "./types";

const ORG_ID = "org-1";
const BASE = `/api/v1/orgs/${ORG_ID}/modules/stakeholders`;

const TYPES: PersonaTypeDefinition[] = [
  { id: "type-primary", organization_id: ORG_ID, name: "Primary", sort_order: 0, is_active: true },
  { id: "type-off", organization_id: ORG_ID, name: "Inactive type", sort_order: 1, is_active: false },
];

function orgPersona(overrides: Partial<Persona> = {}): Persona {
  return buildPersona({ scope: "organization", organization_id: ORG_ID, project_id: null, effective_weight: null, weight_source: null, ...overrides });
}

function mockPanelApis(personas: Persona[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.startsWith(`${BASE}/personas`)) return personas;
    if (path === `${BASE}/persona-types`) return TYPES;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof OrgPersonasPanel> = {
  title: "Modules/Stakeholders/OrgPersonasPanel",
  component: OrgPersonasPanel,
  args: { orgId: ORG_ID },
  decorators: [withRouter("/org-overview"), withToast()],
};
export default meta;

type Story = StoryObj<typeof OrgPersonasPanel>;

export const ListsOrgPersonasWithoutScopeColumn: Story = {
  beforeEach: () => mockPanelApis([orgPersona()]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Field Technician")).toBeInTheDocument());
    await expect(canvas.getByRole("columnheader", { name: "Weight" })).toBeInTheDocument();
    await expect(canvas.queryByRole("columnheader", { name: "Scope" })).not.toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockPanelApis([]),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("No organisation-scoped Personas recorded yet.")).toBeInTheDocument());
  },
};

export const CreateOffersOnlyActiveOrgTypes: Story = {
  beforeEach: () => mockPanelApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New Persona" }));
    await userEvent.click(canvas.getByRole("button", { name: "New Persona" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await expect(within(document.body).getByRole("heading", { name: "New Persona (organisation)" })).toBeInTheDocument();
    await expect(dialog.getByRole("option", { name: "Primary" })).toBeInTheDocument();
    await expect(dialog.queryByRole("option", { name: "Inactive type" })).not.toBeInTheDocument();
  },
};

export const CreatePersona: Story = {
  beforeEach: () => {
    mockPanelApis([]);
    spyOn(api, "post").mockResolvedValue(orgPersona());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New Persona" }));
    await userEvent.click(canvas.getByRole("button", { name: "New Persona" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await userEvent.type(dialog.getByLabelText("Persona name"), "Field Technician");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${BASE}/personas`, expect.objectContaining({ name: "Field Technician" })));
  },
};

export const DarkTheme: Story = { ...ListsOrgPersonasWithoutScopeColumn, globals: { theme: "dark" } };
