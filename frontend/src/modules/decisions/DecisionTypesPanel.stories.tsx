import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { DecisionTypesPanel } from "./DecisionTypesPanel";
import type { DecisionTypeDefinition } from "./types";

const PROJECT_ID = "project-1";

/**
 * `DecisionTypesPanel` fetches and reloads its own list since Phase 9
 * (2026-09-22, moved to Project Admin's `projectAdminSections` — see this
 * panel's own module docstring), so these stories mock the `api` directly
 * rather than wrapping it in a state-owning `Harness`.
 */
function mockDecisionTypeApis(initial: DecisionTypeDefinition[]) {
  let items = initial;
  spyOn(api, "get").mockImplementation(async () => items);
  spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    if (path.endsWith("/decision-types")) {
      const payload = body as { name: string };
      const created: DecisionTypeDefinition = {
        id: `dt-${items.length + 1}`, project_id: PROJECT_ID, name: payload.name, sort_order: items.length,
      };
      items = [...items, created];
      return created;
    }
    if (path.includes("/move")) {
      const id = path.split("/decision-types/")[1].split("/move")[0];
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
    const id = path.split("/decision-types/")[1];
    const payload = body as { name: string };
    items = items.map((i) => (i.id === id ? { ...i, name: payload.name } : i));
    return items.find((i) => i.id === id);
  });
  spyOn(api, "delete").mockImplementation(async (path: string) => {
    const id = path.split("/decision-types/")[1].split("?")[0];
    items = items.filter((i) => i.id !== id);
  });
}

const meta: Meta<typeof DecisionTypesPanel> = {
  title: "Modules/Decisions/DecisionTypesPanel",
  component: DecisionTypesPanel,
  args: { projectId: PROJECT_ID },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof DecisionTypesPanel>;

const SEED: DecisionTypeDefinition[] = [
  { id: "dt-1", project_id: PROJECT_ID, name: "Architecture", sort_order: 0 },
  { id: "dt-2", project_id: PROJECT_ID, name: "Strategy", sort_order: 1 },
];

export const ListsExistingDecisionTypes: Story = {
  beforeEach: () => mockDecisionTypeApis(SEED),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Architecture")).toBeInTheDocument());
    await expect(canvas.getByDisplayValue("Strategy")).toBeInTheDocument();
  },
};

export const AddDecisionType: Story = {
  beforeEach: () => mockDecisionTypeApis([SEED[0]]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByPlaceholderText("Decision type name"));
    await userEvent.type(canvas.getByPlaceholderText("Decision type name"), "Engineering");
    await userEvent.click(canvas.getByRole("button", { name: "Add decision type" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/decisions/decision-types`,
      { name: "Engineering" }
    ));
    await waitFor(() => expect(canvas.getByDisplayValue("Engineering")).toBeInTheDocument());
  },
};

export const DeleteDecisionType: Story = {
  beforeEach: () => mockDecisionTypeApis(SEED),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getAllByRole("button", { name: "Delete decision type" }));
    await userEvent.click(canvas.getAllByRole("button", { name: "Delete decision type" })[0]);

    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/decisions/decision-types/dt-1`
    ));
    await waitFor(() => expect(canvas.queryByDisplayValue("Architecture")).not.toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...ListsExistingDecisionTypes };
export const DarkTheme: Story = { ...ListsExistingDecisionTypes, globals: { theme: "dark" } };
