import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { ProjectPainPointTypesPanel } from "./ProjectPainPointTypesPanel";
import type { EffectivePainPointType } from "./types";

const PROJECT_ID = "project-1";

/** Mirrors `OrgPainPointTypesPanel.stories.tsx`'s own stateful-mock-list
 * harness shape, against the project-scoped endpoints instead. */
function mockProjectTypeApis(initial: EffectivePainPointType[]) {
  let items = initial;
  spyOn(api, "get").mockImplementation(async () => items);
  spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    if (path.endsWith("/pain-point-types")) {
      const payload = body as { name: string; display_order: number | null };
      const created = { id: `local-${items.length + 1}`, name: payload.name, display_order: payload.display_order ?? 0, is_enabled: true, source: "project_local" as const };
      items = [...items, created];
      return created;
    }
    throw new Error(`unmocked POST: ${path}`);
  });
  spyOn(api, "put").mockImplementation(async (path: string, body?: unknown) => {
    const id = path.split("/pain-point-types/")[1];
    const payload = body as { name?: string; display_order?: number; is_enabled?: boolean };
    items = items.map((i) => (i.id === id ? { ...i, ...payload, source: i.source === "org" ? "project_override" : i.source } : i));
    return items.find((i) => i.id === id);
  });
  spyOn(api, "delete").mockImplementation(async (path: string) => {
    const id = path.split("/pain-point-types/")[1];
    const inUse = items.find((i) => i.id === id)?.name === "Field team";
    if (inUse) throw new ApiError(409, "1 Pain Point still references this type.");
    items = items.filter((i) => i.id !== id);
  });
}

const meta: Meta<typeof ProjectPainPointTypesPanel> = {
  title: "Modules/ContextStrategy/ProjectPainPointTypesPanel",
  component: ProjectPainPointTypesPanel,
  args: { projectId: PROJECT_ID },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof ProjectPainPointTypesPanel>;

export const ListsEffectiveTypes: Story = {
  beforeEach: () => mockProjectTypeApis([
    { id: "type-market", name: "Market", display_order: 0, is_enabled: true, source: "org" },
    { id: "override-1", name: "Frontline User", display_order: 1, is_enabled: true, source: "project_override" },
    { id: "local-1", name: "Field team", display_order: 2, is_enabled: true, source: "project_local" },
  ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Market")).toBeInTheDocument());
    await expect(canvas.getByDisplayValue("Frontline User")).toBeInTheDocument();
    await expect(canvas.getByDisplayValue("Field team")).toBeInTheDocument();
    await expect(canvas.getByText("Org default")).toBeInTheDocument();
    await expect(canvas.getByText("Org default (overridden)")).toBeInTheDocument();
    await expect(canvas.getByText("Project only")).toBeInTheDocument();
  },
};

export const RenameOrgTypeCreatesOverride: Story = {
  beforeEach: () => mockProjectTypeApis([{ id: "type-market", name: "Market", display_order: 0, is_enabled: true, source: "org" }]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = await canvas.findByDisplayValue("Market");
    await userEvent.clear(input);
    await userEvent.type(input, "Customer");
    await userEvent.click(canvas.getByRole("button", { name: "Rename" }));

    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/pain-point-types/type-market`, { name: "Customer" }
    ));
    await waitFor(() => expect(canvas.getByText("Org default (overridden)")).toBeInTheDocument());
  },
};

export const AddProjectLocalType: Story = {
  beforeEach: () => mockProjectTypeApis([{ id: "type-market", name: "Market", display_order: 0, is_enabled: true, source: "org" }]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByPlaceholderText("Project Pain Point type name"));
    await userEvent.type(canvas.getByPlaceholderText("Project Pain Point type name"), "Field team");
    await userEvent.click(canvas.getByRole("button", { name: "Add project-only Pain Point type" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/pain-point-types`, { name: "Field team", display_order: 1 }
    ));
    await waitFor(() => expect(canvas.getByDisplayValue("Field team")).toBeInTheDocument());
  },
};

export const ToggleEnabledState: Story = {
  beforeEach: () => mockProjectTypeApis([{ id: "local-1", name: "Field team", display_order: 0, is_enabled: true, source: "project_local" }]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const toggle = await canvas.findByRole("switch", { name: "Enabled: Field team" });
    await expect(toggle).toHaveAttribute("aria-checked", "true");

    await userEvent.click(toggle);

    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/pain-point-types/local-1`, { is_enabled: false }
    ));
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "false"));
  },
};

export const CannotDeleteUntouchedOrgDefault: Story = {
  beforeEach: () => mockProjectTypeApis([
    { id: "type-market", name: "Market", display_order: 0, is_enabled: true, source: "org" },
    { id: "local-1", name: "Field team", display_order: 1, is_enabled: true, source: "project_local" },
  ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByDisplayValue("Market"));
    const marketRow = canvas.getByDisplayValue("Market").closest("div")!.parentElement!;
    await userEvent.click(within(marketRow).getByRole("button", { name: "Delete Pain Point type" }));

    await waitFor(() => expect(
      canvas.getByText(/there is nothing to delete. Disable it instead/)
    ).toBeInTheDocument());
  },
};

export const DeleteBlockedWhileInUse: Story = {
  beforeEach: () => mockProjectTypeApis([
    { id: "local-1", name: "Field team", display_order: 0, is_enabled: true, source: "project_local" },
    { id: "local-2", name: "Spare type", display_order: 1, is_enabled: true, source: "project_local" },
  ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByDisplayValue("Field team"));
    const row = canvas.getByDisplayValue("Field team").closest("div")!.parentElement!;
    await userEvent.click(within(row).getByRole("button", { name: "Delete Pain Point type" }));

    await waitFor(() => expect(
      canvas.getByText("This type is still used by at least one Pain Point in this project. Disable it instead of deleting it.")
    ).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...ListsEffectiveTypes };
export const DarkTheme: Story = { ...ListsEffectiveTypes, globals: { theme: "dark" } };
