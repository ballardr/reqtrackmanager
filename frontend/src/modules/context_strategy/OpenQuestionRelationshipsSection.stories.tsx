import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { withToast } from "../../testing/storybook-helpers";
import { projectOpenQuestionApi, projectStrategyApi } from "./api";
import { OpenQuestionRelationshipsSection } from "./OpenQuestionRelationshipsSection";
import type { ContextStrategyLink, OpenQuestion } from "./types";

const PROJECT_ID = "project-1";

function openQuestion(overrides: Partial<OpenQuestion> = {}): OpenQuestion {
  return {
    id: "open-question-1", project_id: PROJECT_ID, creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null,
    question: "Should we standardise on a single battery vendor?",
    context: "", evidence: "",
    priority: "high", status: "investigating", owner_id: null, due_date: null, is_locked: false,
    created_at: "2026-01-05T09:00:00Z", updated_at: "2026-01-05T09:00:00Z",
    ...overrides,
  };
}

function link(overrides: Partial<ContextStrategyLink> = {}): ContextStrategyLink {
  return {
    id: "link-1", source_type: "open_question", source_id: "open-question-1", target_type: "strategy",
    target_id: "strategy-1", link_type_id: null, direction: "outgoing", display_name: "Related to",
    other_type: "strategy", other_id: "strategy-1", other_display_code: null, other_display_name: "Lead the regional market",
    created_by: "user-1", created_at: "2026-01-06T09:00:00Z",
    ...overrides,
  };
}

const meta: Meta<typeof OpenQuestionRelationshipsSection> = {
  title: "Modules/ContextStrategy/OpenQuestionRelationshipsSection",
  component: OpenQuestionRelationshipsSection,
  args: { projectId: PROJECT_ID, openQuestion: openQuestion() },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof OpenQuestionRelationshipsSection>;

export const NoRelationshipsYet: Story = {
  beforeEach: () => {
    spyOn(projectOpenQuestionApi, "listRelationships").mockResolvedValue([]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No relationships yet.")).toBeInTheDocument());
  },
};

export const ListsExistingRelationships: Story = {
  beforeEach: () => {
    spyOn(projectOpenQuestionApi, "listRelationships").mockResolvedValue([link()]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Lead the regional market")).toBeInTheDocument());
    await expect(canvas.getByText("Related to")).toBeInTheDocument();
  },
};

export const AddRelatedToStrategyRelationship: Story = {
  beforeEach: () => {
    spyOn(projectOpenQuestionApi, "listRelationships").mockResolvedValue([]);
    spyOn(projectStrategyApi, "list").mockResolvedValue([
      {
        id: "strategy-2", scope: "project", organization_id: null, project_id: PROJECT_ID, creator_id: "user-1",
        is_archived: false, archived_at: null, archived_by: null, title: "Modernise the delivery pipeline",
        objective: "", current_state: "", desired_future_state: "", rationale: "", expected_outcomes: "",
        constraints: "", measures_of_success: "", priority: "medium", time_horizon: "medium_term", status: "active",
        version_number: 1, is_locked: false, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
      },
    ]);
    spyOn(projectOpenQuestionApi, "createRelationship").mockResolvedValue(link({ id: "link-2" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Strategy"));
    await userEvent.selectOptions(canvas.getByLabelText("Strategy"), "strategy-2");
    await userEvent.click(canvas.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(projectOpenQuestionApi.createRelationship).toHaveBeenCalledWith(
      PROJECT_ID, "open-question-1", "related_to_strategy", "strategy-2"
    ));
  },
};

export const LightTheme: Story = { ...ListsExistingRelationships };
export const DarkTheme: Story = { ...ListsExistingRelationships, globals: { theme: "dark" } };
