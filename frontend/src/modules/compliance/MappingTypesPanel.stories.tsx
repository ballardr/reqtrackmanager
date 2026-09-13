import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { MappingTypesPanel } from "./MappingTypesPanel";
import type { ComplianceMappingRelationshipType } from "./types";

const ORG_ID = "org-1";

/**
 * Unlike `ActionTypesPanel`, `MappingTypesPanel` owns its own fetch/reload
 * state entirely (only `orgId` is a prop) — see its own docstring. So,
 * unlike that panel's story, no harness is needed here: mocking `api.*`
 * directly is enough for a real round trip. `DefinitionList`'s own generic
 * rename/reorder/delete mechanics are already covered by
 * `DefinitionList.stories.tsx`; these stories exercise what's specific to
 * this panel — wiring to the compliance mapping-relationship-type
 * endpoints, and its `renderExtra` `implies_equivalence` toggle (a plain
 * boolean `DefinitionList` fields can't express on its own, see
 * `DefinitionList.stories.tsx`'s own `WithRenderExtra` story for the
 * generic slot mechanics).
 */
function mockMappingTypeApis(initial: ComplianceMappingRelationshipType[]) {
  let items = initial;
  spyOn(api, "get").mockImplementation(async () => items);
  spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    if (path.endsWith("/mapping-relationship-types")) {
      const payload = body as { name: string; implies_equivalence: boolean };
      const created: ComplianceMappingRelationshipType = {
        id: `mt-${items.length + 1}`, organization_id: ORG_ID, name: payload.name,
        sort_order: items.length, implies_equivalence: payload.implies_equivalence,
      };
      items = [...items, created];
      return created;
    }
    if (path.includes("/move")) {
      const id = path.split("/mapping-relationship-types/")[1].split("/move")[0];
      const direction = (body as { direction: "up" | "down" }).direction;
      const idx = items.findIndex((i) => i.id === id);
      const swapWith = direction === "up" ? idx - 1 : idx + 1;
      if (swapWith >= 0 && swapWith < items.length) {
        const next = [...items];
        [next[idx], next[swapWith]] = [next[swapWith], next[idx]];
        items = next;
      }
      return items.find((i) => i.id === id);
    }
    throw new Error(`unmocked POST: ${path}`);
  });
  spyOn(api, "patch").mockImplementation(async (path: string, body?: unknown) => {
    const id = path.split("/mapping-relationship-types/")[1];
    const payload = body as { name: string; implies_equivalence: boolean };
    items = items.map((i) => (i.id === id ? { ...i, ...payload } : i));
    return items.find((i) => i.id === id);
  });
  spyOn(api, "delete").mockImplementation(async (path: string) => {
    const id = path.split("/mapping-relationship-types/")[1].split("?")[0];
    items = items.filter((i) => i.id !== id);
  });
}

const meta: Meta<typeof MappingTypesPanel> = {
  title: "Modules/Compliance/MappingTypesPanel",
  component: MappingTypesPanel,
  args: { orgId: ORG_ID },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof MappingTypesPanel>;

export const ListsExistingRelationshipTypes: Story = {
  beforeEach: () => mockMappingTypeApis([
    { id: "mt-1", organization_id: ORG_ID, name: "Equivalent", sort_order: 0, implies_equivalence: false },
    { id: "mt-2", organization_id: ORG_ID, name: "Satisfies", sort_order: 1, implies_equivalence: false },
  ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Equivalent")).toBeInTheDocument());
    await expect(canvas.getByDisplayValue("Satisfies")).toBeInTheDocument();
  },
};

export const AddRelationshipTypeDefaultsImpliesEquivalenceFalse: Story = {
  beforeEach: () => mockMappingTypeApis([{ id: "mt-1", organization_id: ORG_ID, name: "Equivalent", sort_order: 0, implies_equivalence: false }]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByPlaceholderText("Relationship type name")).toBeInTheDocument());
    await userEvent.type(canvas.getByPlaceholderText("Relationship type name"), "Derived from");
    await userEvent.click(canvas.getByRole("button", { name: "Add relationship type" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/compliance/mapping-relationship-types`,
      { name: "Derived from", implies_equivalence: false }
    ));
    await waitFor(() => expect(canvas.getByDisplayValue("Derived from")).toBeInTheDocument());
  },
};

export const ToggleImpliesEquivalenceKeepsNameUnchanged: Story = {
  beforeEach: () => mockMappingTypeApis([{ id: "mt-1", organization_id: ORG_ID, name: "Equivalent", sort_order: 0, implies_equivalence: false }]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const toggle = await canvas.findByRole("switch", { name: "Implies equivalence for Equivalent" });
    await expect(toggle).toHaveAttribute("aria-checked", "false");

    await userEvent.click(toggle);

    // Toggling sends both fields together (a single PATCH endpoint) — the
    // name must round-trip unchanged, per this component's own docstring
    // ("each handler always sends the other field's current, unchanged
    // value alongside the one it's actually changing").
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/compliance/mapping-relationship-types/mt-1`,
      { name: "Equivalent", implies_equivalence: true }
    ));
    await waitFor(async () => expect(toggle).toHaveAttribute("aria-checked", "true"));
  },
};

export const RenameKeepsImpliesEquivalenceUnchanged: Story = {
  beforeEach: () => mockMappingTypeApis([{ id: "mt-1", organization_id: ORG_ID, name: "Equivalent", sort_order: 0, implies_equivalence: true }]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = await canvas.findByDisplayValue("Equivalent");
    await userEvent.clear(input);
    await userEvent.type(input, "Equivalent to");
    await userEvent.click(canvas.getByRole("button", { name: "Rename" }));

    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/compliance/mapping-relationship-types/mt-1`,
      { name: "Equivalent to", implies_equivalence: true }
    ));
  },
};

export const LoadErrorShowsInlineMessage: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new ApiError(404, "Compliance module is not enabled for this organisation."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() =>
      expect(canvas.getByText("Compliance module is not enabled for this organisation.")).toBeInTheDocument()
    );
  },
};

export const LightTheme: Story = { ...ListsExistingRelationshipTypes };
export const DarkTheme: Story = { ...ListsExistingRelationshipTypes, globals: { theme: "dark" } };
