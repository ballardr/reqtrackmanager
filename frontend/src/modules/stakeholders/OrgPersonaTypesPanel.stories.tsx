import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { OrgPersonaTypesPanel } from "./OrgPersonaTypesPanel";
import type { PersonaTypeDefinition } from "./types";

const ORG_ID = "org-1";

/** A stateful in-memory list behind mocked `api.*` calls, as the Pain Point panel's stories do. */
function mockOrgTypeApis(initial: PersonaTypeDefinition[]) {
  let items = initial;
  spyOn(api, "get").mockImplementation(async () => items);
  spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    if (path.endsWith("/persona-types")) {
      const created: PersonaTypeDefinition = {
        id: `type-${items.length + 1}`, organization_id: ORG_ID, name: (body as { name: string }).name,
        sort_order: items.length, is_active: true,
      };
      items = [...items, created];
      return created;
    }
    throw new Error(`unmocked POST: ${path}`);
  });
  spyOn(api, "patch").mockImplementation(async (path: string, body?: unknown) => {
    const id = path.split("/persona-types/")[1];
    items = items.map((i) => (i.id === id ? { ...i, ...(body as object) } : i));
    return items.find((i) => i.id === id);
  });
  spyOn(api, "delete").mockImplementation(async (path: string) => {
    const id = path.split("/persona-types/")[1];
    if (items.find((i) => i.id === id)?.name === "Negative") throw new ApiError(409, "In use.");
    items = items.filter((i) => i.id !== id);
  });
}

const DEFAULTS: PersonaTypeDefinition[] = [
  { id: "type-primary", organization_id: ORG_ID, name: "Primary", sort_order: 0, is_active: true },
  { id: "type-secondary", organization_id: ORG_ID, name: "Secondary", sort_order: 1, is_active: true },
  { id: "type-negative", organization_id: ORG_ID, name: "Negative", sort_order: 2, is_active: true },
];

const meta: Meta<typeof OrgPersonaTypesPanel> = {
  title: "Modules/Stakeholders/OrgPersonaTypesPanel",
  component: OrgPersonaTypesPanel,
  args: { orgId: ORG_ID },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof OrgPersonaTypesPanel>;

export const ListsDefaultTypes: Story = {
  beforeEach: () => mockOrgTypeApis(DEFAULTS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Primary")).toBeInTheDocument());
    await expect(canvas.getByDisplayValue("Secondary")).toBeInTheDocument();
    await expect(canvas.getByDisplayValue("Negative")).toBeInTheDocument();
  },
};

export const AddType: Story = {
  beforeEach: () => mockOrgTypeApis(DEFAULTS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByPlaceholderText("Persona type name"));
    await userEvent.type(canvas.getByPlaceholderText("Persona type name"), "Edge case");
    await userEvent.click(canvas.getByRole("button", { name: "Add Persona type" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/modules/stakeholders/persona-types`, { name: "Edge case" }),
    );
    await waitFor(() => expect(canvas.getByDisplayValue("Edge case")).toBeInTheDocument());
  },
};

export const DeleteInUseExplainsProjectsAndPersonas: Story = {
  beforeEach: () => mockOrgTypeApis(DEFAULTS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByDisplayValue("Negative"));
    const row = canvas.getByDisplayValue("Negative").closest("div")!.parentElement!;
    await userEvent.click(within(row).getByRole("button", { name: "Delete Persona type" }));
    await waitFor(() =>
      expect(canvas.getByText("This type is still used by at least one project or persona. Disable it instead of deleting it.")).toBeInTheDocument(),
    );
  },
};

export const DarkTheme: Story = { ...ListsDefaultTypes, globals: { theme: "dark" } };
