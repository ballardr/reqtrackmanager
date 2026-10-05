import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { OrgStakeholderTypesPanel } from "./OrgStakeholderTypesPanel";
import type { PersonaTypeDefinition } from "./types";

const ORG_ID = "org-1";

/** A stateful in-memory list behind mocked `api.*` calls, as the Persona type panel's stories do. */
function mockOrgTypeApis(initial: PersonaTypeDefinition[]) {
  let items = initial;
  spyOn(api, "get").mockImplementation(async () => items);
  spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    if (path.endsWith("/stakeholder-types")) {
      const created: PersonaTypeDefinition = {
        id: `type-${items.length + 1}`, organization_id: ORG_ID, name: (body as { name: string }).name,
        sort_order: items.length, is_active: true,
      };
      items = [...items, created];
      return created;
    }
    throw new Error(`unmocked POST: ${path}`);
  });
  spyOn(api, "delete").mockImplementation(async (path: string) => {
    const id = path.split("/stakeholder-types/")[1];
    if (items.find((i) => i.id === id)?.name === "Regulator") throw new ApiError(409, "In use.");
    items = items.filter((i) => i.id !== id);
  });
}

const DEFAULTS: PersonaTypeDefinition[] = [
  { id: "type-customer", organization_id: ORG_ID, name: "Customer", sort_order: 0, is_active: true },
  { id: "type-regulator", organization_id: ORG_ID, name: "Regulator", sort_order: 1, is_active: true },
];

const meta: Meta<typeof OrgStakeholderTypesPanel> = {
  title: "Modules/Stakeholders/OrgStakeholderTypesPanel",
  component: OrgStakeholderTypesPanel,
  args: { orgId: ORG_ID },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof OrgStakeholderTypesPanel>;

export const ListsTypes: Story = {
  beforeEach: () => mockOrgTypeApis(DEFAULTS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Customer")).toBeInTheDocument());
    await expect(canvas.getByDisplayValue("Regulator")).toBeInTheDocument();
  },
};

export const AddType: Story = {
  beforeEach: () => mockOrgTypeApis(DEFAULTS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByPlaceholderText("Stakeholder type name"));
    await userEvent.type(canvas.getByPlaceholderText("Stakeholder type name"), "Investor");
    await userEvent.click(canvas.getByRole("button", { name: "Add Stakeholder type" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/modules/stakeholders/stakeholder-types`, { name: "Investor" }),
    );
    await waitFor(() => expect(canvas.getByDisplayValue("Investor")).toBeInTheDocument());
  },
};

export const DeleteInUseExplainsProjectsAndStakeholders: Story = {
  beforeEach: () => mockOrgTypeApis(DEFAULTS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByDisplayValue("Regulator"));
    const row = canvas.getByDisplayValue("Regulator").closest("div")!.parentElement!;
    await userEvent.click(within(row).getByRole("button", { name: "Delete Stakeholder type" }));
    await waitFor(() =>
      expect(canvas.getByText("This type is still used by at least one project or stakeholder. Disable it instead of deleting it.")).toBeInTheDocument(),
    );
  },
};

export const DarkTheme: Story = { ...ListsTypes, globals: { theme: "dark" } };
