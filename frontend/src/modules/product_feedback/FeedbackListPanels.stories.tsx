import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import type { EffectiveTypeRow } from "../../components/TypeVocabularyPanels";
import { withToast } from "../../testing/storybook-helpers";
import { ProjectRequestChannelsPanel } from "./FeedbackListPanels";

const CHANNELS: EffectiveTypeRow[] = [
  { id: "c1", name: "Support ticket", display_order: 0, is_enabled: true, source: "org" },
  { id: "c2", name: "Hallway", display_order: 1, is_enabled: true, source: "project_local" },
];

const meta: Meta = { title: "Modules/ProductFeedback/FeedbackListPanels", decorators: [withToast()] };
export default meta;

type Story = StoryObj;

/** A project's channels list shows its own entry beside the organisation's, and deleting its own entry deletes it. */
export const ProjectChannelsListOrganisationAndOwnEntries: Story = {
  render: () => <ProjectRequestChannelsPanel projectId="project-1" />,
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => (path.endsWith("/hidden") ? [] : CHANNELS) as never);
    spyOn(api, "delete").mockResolvedValue(undefined as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Support ticket")).toBeInTheDocument());
    await expect(canvas.getByDisplayValue("Hallway")).toBeInTheDocument();
    await expect(canvas.getByText("Org default")).toBeInTheDocument();
    await expect(canvas.getByText("Project only")).toBeInTheDocument();
  },
};
