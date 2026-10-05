import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { ProjectPersonaTypesPanel } from "./ProjectPersonaTypesPanel";
import type { EffectivePersonaType } from "./types";

const PROJECT_ID = "project-1";
const BASE = `/api/v1/projects/${PROJECT_ID}/modules/stakeholders/persona-types`;

function mockProjectTypeApis(initial: EffectivePersonaType[]) {
  let items = initial;
  spyOn(api, "get").mockImplementation(async () => items);
  spyOn(api, "post").mockImplementation(async (_path: string, body?: unknown) => {
    const payload = body as { name: string; display_order: number | null };
    items = [...items, { id: `local-${items.length + 1}`, name: payload.name, display_order: payload.display_order ?? 0, is_enabled: true, source: "project_local" }];
    return items[items.length - 1];
  });
  spyOn(api, "put").mockImplementation(async (path: string, body?: unknown) => {
    const id = path.split("/persona-types/")[1];
    const payload = body as { name?: string; is_enabled?: boolean };
    items = items.map((i) =>
      i.id === id
        ? { ...i, name: payload.name ?? i.name, is_enabled: payload.is_enabled ?? i.is_enabled, source: i.source === "org" ? "project_override" : i.source }
        : i,
    );
    return items.find((i) => i.id === id);
  });
}

const meta: Meta<typeof ProjectPersonaTypesPanel> = {
  title: "Modules/Stakeholders/ProjectPersonaTypesPanel",
  component: ProjectPersonaTypesPanel,
  args: { projectId: PROJECT_ID },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof ProjectPersonaTypesPanel>;

const BASELINE: EffectivePersonaType[] = [
  { id: "type-primary", name: "Primary", display_order: 0, is_enabled: true, source: "org" },
  { id: "local-1", name: "Field only", display_order: 1, is_enabled: true, source: "project_local" },
];

export const ListsEffectiveTypes: Story = {
  beforeEach: () => mockProjectTypeApis(BASELINE),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Primary")).toBeInTheDocument());
    await expect(canvas.getByDisplayValue("Field only")).toBeInTheDocument();
    await expect(canvas.getByText("Org default")).toBeInTheDocument();
    await expect(canvas.getByText("Project only")).toBeInTheDocument();
  },
};

export const RenameCreatesOverride: Story = {
  beforeEach: () => mockProjectTypeApis(BASELINE),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = await canvas.findByDisplayValue("Primary");
    await userEvent.clear(input);
    await userEvent.type(input, "Core user");
    await userEvent.click(within(input.closest("div")!.parentElement!).getByRole("button", { name: "Rename" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${BASE}/type-primary`, { name: "Core user" }));
  },
};

export const AddProjectOnlyType: Story = {
  beforeEach: () => mockProjectTypeApis(BASELINE),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByPlaceholderText("Project Persona type name"));
    await userEvent.type(canvas.getByPlaceholderText("Project Persona type name"), "Contractor");
    await userEvent.click(canvas.getByRole("button", { name: "Add project-only Persona type" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(BASE, { name: "Contractor", display_order: 2 }));
    await waitFor(() => expect(canvas.getByDisplayValue("Contractor")).toBeInTheDocument());
  },
};

export const DarkTheme: Story = { ...ListsEffectiveTypes, globals: { theme: "dark" } };
