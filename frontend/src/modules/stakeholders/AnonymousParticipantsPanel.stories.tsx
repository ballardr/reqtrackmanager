import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { AnonymousParticipantsPanel } from "./AnonymousParticipantsPanel";
import type { AnonymousParticipant } from "./types";

const BASE = "/api/v1/projects/project-1/modules/stakeholders/engagements/engagement-1/anonymous-participants";

const PARTICIPANTS: AnonymousParticipant[] = [
  { id: "ap1", engagement_id: "engagement-1", label: "Participant 1", persona_id: "persona-1", persona_name: "Field Technician" },
  { id: "ap2", engagement_id: "engagement-1", label: "Participant 2", persona_id: null, persona_name: null },
];

function mockParticipants(rows: AnonymousParticipant[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === BASE) return rows;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof AnonymousParticipantsPanel> = {
  title: "Modules/Stakeholders/AnonymousParticipantsPanel",
  component: AnonymousParticipantsPanel,
  decorators: [withToast()],
  args: {
    projectId: "project-1", engagementId: "engagement-1",
    personaOptions: [{ value: "persona-1", label: "Field Technician" }],
  },
};
export default meta;

type Story = StoryObj<typeof AnonymousParticipantsPanel>;

export const ListsLabelsWithTheirPersona: Story = {
  beforeEach: () => mockParticipants(PARTICIPANTS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Participant 1 · Field Technician")).toBeInTheDocument());
    await expect(canvas.getByText("Participant 2")).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockParticipants([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No anonymous participants.")).toBeInTheDocument());
    // The "use a label, not a name" guidance is in the add form.
    await userEvent.click(canvas.getByRole("button", { name: "Add to Anonymous participants" }));
    await expect(within(document.body).getByText(/not a name/)).toBeInTheDocument();
  },
};

export const AddsAParticipantWithAPersona: Story = {
  beforeEach: () => {
    mockParticipants([]);
    spyOn(api, "post").mockResolvedValue(PARTICIPANTS[0]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Add to Anonymous participants" }));
    await userEvent.click(canvas.getByRole("button", { name: "Add to Anonymous participants" }));
    const popover = within(within(document.body).getByRole("dialog", { name: "Add to Anonymous participants" }));
    await expect(popover.getByRole("button", { name: "Add participant" })).toBeDisabled();
    await userEvent.type(popover.getByLabelText("Participant label"), "Participant 1");
    await userEvent.selectOptions(popover.getByLabelText("Persona represented"), "persona-1");
    await userEvent.click(popover.getByRole("button", { name: "Add participant" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(BASE, { label: "Participant 1", persona_id: "persona-1" }));
  },
};

export const RemovesBehindAConfirm: Story = {
  beforeEach: () => {
    mockParticipants(PARTICIPANTS);
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Remove Participant 2" }));
    await userEvent.click(canvas.getByRole("button", { name: "Remove Participant 2" }));
    await userEvent.click(within(within(document.body).getByRole("dialog", { name: "Remove Participant 2?" })).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${BASE}/ap2`));
  },
};

export const DarkTheme: Story = { ...ListsLabelsWithTheirPersona, globals: { theme: "dark" } };
