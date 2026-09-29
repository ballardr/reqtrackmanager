import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { OrgPainPointTypesPanel } from "./OrgPainPointTypesPanel";
import type { PainPointTypeDefinition } from "./types";

const ORG_ID = "org-1";

/**
 * Mirrors `modules/compliance/MappingTypesPanel.stories.tsx`'s own harness
 * shape (a stateful in-memory list behind mocked `api.*` calls) — this
 * panel, like that one, owns its own fetch/reload state entirely.
 */
function mockOrgTypeApis(initial: PainPointTypeDefinition[]) {
  let items = initial;
  spyOn(api, "get").mockImplementation(async () => items);
  spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    if (path.endsWith("/pain-point-types")) {
      const payload = body as { name: string };
      const created: PainPointTypeDefinition = {
        id: `type-${items.length + 1}`, organization_id: ORG_ID, name: payload.name,
        sort_order: items.length, is_active: true,
      };
      items = [...items, created];
      return created;
    }
    if (path.includes("/move")) {
      const id = path.split("/pain-point-types/")[1].split("/move")[0];
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
    const id = path.split("/pain-point-types/")[1];
    const payload = body as { name?: string; is_active?: boolean };
    items = items.map((i) => (i.id === id ? { ...i, ...payload } : i));
    return items.find((i) => i.id === id);
  });
  spyOn(api, "delete").mockImplementation(async (path: string) => {
    const id = path.split("/pain-point-types/")[1];
    const referenced = items.find((i) => i.id === id)?.name === "Operator";
    if (referenced) throw new ApiError(409, "1 project still references this type.");
    items = items.filter((i) => i.id !== id);
  });
}

const meta: Meta<typeof OrgPainPointTypesPanel> = {
  title: "Modules/ContextStrategy/OrgPainPointTypesPanel",
  component: OrgPainPointTypesPanel,
  args: { orgId: ORG_ID },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof OrgPainPointTypesPanel>;

export const ListsDefaultTypes: Story = {
  beforeEach: () => mockOrgTypeApis([
    { id: "type-market", organization_id: ORG_ID, name: "Market", sort_order: 0, is_active: true },
    { id: "type-user", organization_id: ORG_ID, name: "User", sort_order: 1, is_active: true },
    { id: "type-operator", organization_id: ORG_ID, name: "Operator", sort_order: 2, is_active: true },
  ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Market")).toBeInTheDocument());
    await expect(canvas.getByDisplayValue("User")).toBeInTheDocument();
    await expect(canvas.getByDisplayValue("Operator")).toBeInTheDocument();
  },
};

export const AddType: Story = {
  beforeEach: () => mockOrgTypeApis([{ id: "type-market", organization_id: ORG_ID, name: "Market", sort_order: 0, is_active: true }]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByPlaceholderText("Pain Point type name"));
    await userEvent.type(canvas.getByPlaceholderText("Pain Point type name"), "Regulatory");
    await userEvent.click(canvas.getByRole("button", { name: "Add Pain Point type" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/context_strategy/pain-point-types`, { name: "Regulatory" }
    ));
    await waitFor(() => expect(canvas.getByDisplayValue("Regulatory")).toBeInTheDocument());
  },
};

export const ToggleActiveState: Story = {
  beforeEach: () => mockOrgTypeApis([{ id: "type-market", organization_id: ORG_ID, name: "Market", sort_order: 0, is_active: true }]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const toggle = await canvas.findByRole("switch", { name: "Active: Market" });
    await expect(toggle).toHaveAttribute("aria-checked", "true");

    await userEvent.click(toggle);

    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/context_strategy/pain-point-types/type-market`, { is_active: false }
    ));
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "false"));
  },
};

export const DeleteBlockedWhileInUseShowsPlainError: Story = {
  beforeEach: () => mockOrgTypeApis([
    { id: "type-market", organization_id: ORG_ID, name: "Market", sort_order: 0, is_active: true },
    { id: "type-operator", organization_id: ORG_ID, name: "Operator", sort_order: 1, is_active: true },
  ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByDisplayValue("Operator"));
    // Both delete buttons share the same accessible name ("Delete Pain Point
    // type") — pick the row belonging to "Operator" specifically.
    const operatorRow = canvas.getByDisplayValue("Operator").closest("div")!.parentElement!;
    await userEvent.click(within(operatorRow).getByRole("button", { name: "Delete Pain Point type" }));

    // A plain error banner, not `DefinitionList`'s reassign-target picker —
    // this org tier's own delete has no reassignment concept (see this
    // component's own docstring).
    await waitFor(() => expect(
      canvas.getByText("This type is still used by at least one project. Disable it instead of deleting it.")
    ).toBeInTheDocument());
    await expect(canvas.queryByText(/Reassign/)).not.toBeInTheDocument();
  },
};

export const LoadErrorShowsInlineMessage: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new ApiError(404, "Context & Strategy module is not enabled for this organisation."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() =>
      expect(canvas.getByText("Context & Strategy module is not enabled for this organisation.")).toBeInTheDocument()
    );
  },
};

export const LightTheme: Story = { ...ListsDefaultTypes };
export const DarkTheme: Story = { ...ListsDefaultTypes, globals: { theme: "dark" } };
