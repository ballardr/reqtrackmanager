import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { ResearchPromptsPanel } from "./ResearchPromptsPanel";
import type { EngagementPrompt } from "./types";

const BASE = "/api/v1/projects/project-1/modules/stakeholders/engagements/engagement-1/prompts";

const PROMPTS: EngagementPrompt[] = [
  { id: "p1", engagement_id: "engagement-1", sort_order: 0, prompt: "Walk me through a typical inspection", response_notes: "Starts with the checklist." },
  { id: "p2", engagement_id: "engagement-1", sort_order: 1, prompt: "What slows you down?", response_notes: "" },
];

function mockPrompts(prompts: EngagementPrompt[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === BASE) return prompts;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof ResearchPromptsPanel> = {
  title: "Modules/Stakeholders/ResearchPromptsPanel",
  component: ResearchPromptsPanel,
  decorators: [withToast()],
  args: { projectId: "project-1", engagementId: "engagement-1" },
};
export default meta;

type Story = StoryObj<typeof ResearchPromptsPanel>;

export const ListsPromptsInOrderWithTheirNotes: Story = {
  beforeEach: () => mockPrompts(PROMPTS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Walk me through a typical inspection")).toBeInTheDocument());
    await expect(canvas.getByText("Starts with the checklist.")).toBeInTheDocument();
    // The first cannot move up and the last cannot move down.
    await expect(canvas.getByRole("button", { name: "Move Walk me through a typical inspection up" })).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "Move What slows you down? down" })).toBeDisabled();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockPrompts([]),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("No session prompts yet.")).toBeInTheDocument());
  },
};

export const AddsAPrompt: Story = {
  beforeEach: () => {
    mockPrompts([]);
    spyOn(api, "post").mockResolvedValue(PROMPTS[0]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("New session prompt"));
    await expect(canvas.getByRole("button", { name: "Add prompt" })).toBeDisabled();
    await userEvent.type(canvas.getByLabelText("New session prompt"), "What slows you down?");
    await userEvent.click(canvas.getByRole("button", { name: "Add prompt" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(BASE, { prompt: "What slows you down?" }));
    await waitFor(() => expect(within(document.body).getByText("Prompt added.")).toBeInTheDocument());
  },
};

export const MovesAPromptDown: Story = {
  beforeEach: () => {
    mockPrompts(PROMPTS);
    spyOn(api, "post").mockResolvedValue(PROMPTS);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Move Walk me through a typical inspection down" }));
    await userEvent.click(canvas.getByRole("button", { name: "Move Walk me through a typical inspection down" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${BASE}/p1/move`, { direction: "down" }));
  },
};

export const EditsTheNotesInAModal: Story = {
  beforeEach: () => {
    mockPrompts(PROMPTS);
    spyOn(api, "patch").mockResolvedValue(PROMPTS[1]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Edit What slows you down?" }));
    await userEvent.click(canvas.getByRole("button", { name: "Edit What slows you down?" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Edit session prompt" }));
    await userEvent.type(dialog.getByLabelText("Response notes"), "Waiting for sign-off");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith(`${BASE}/p2`, { prompt: "What slows you down?", response_notes: "Waiting for sign-off" }),
    );
  },
};

export const DeletesBehindAConfirm: Story = {
  beforeEach: () => {
    mockPrompts(PROMPTS);
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Delete What slows you down?" }));
    await userEvent.click(canvas.getByRole("button", { name: "Delete What slows you down?" }));
    await userEvent.click(within(within(document.body).getByRole("dialog", { name: "Delete this session prompt?" })).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${BASE}/p2`));
  },
};

export const DarkTheme: Story = { ...ListsPromptsInOrderWithTheirNotes, globals: { theme: "dark" } };
