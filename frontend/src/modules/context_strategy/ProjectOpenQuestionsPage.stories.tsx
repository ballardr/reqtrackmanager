import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildProject, withRouter, withToast } from "../../testing/storybook-helpers";
import { ProjectOpenQuestionsPage } from "./ProjectOpenQuestionsPage";
import type { OpenQuestion } from "./types";

const PROJECT_ID = "project-1";

function openQuestion(overrides: Partial<OpenQuestion> = {}): OpenQuestion {
  return {
    id: "open-question-1", project_id: PROJECT_ID, creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null,
    question: "Should we standardise on a single battery vendor?",
    context: "Two vendors are currently qualified.", evidence: "",
    priority: "high", status: "open", owner_id: null, due_date: "2026-03-01", is_locked: false,
    created_at: "2026-01-05T09:00:00Z", updated_at: "2026-01-05T09:00:00Z",
    ...overrides,
  };
}

function mockPageApis(openQuestions: OpenQuestion[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/projects/${PROJECT_ID}`) return buildProject({ id: PROJECT_ID, organization_id: "org-1" });
    if (path.startsWith(`/api/v1/projects/${PROJECT_ID}/modules/context_strategy/open-questions`)) return openQuestions;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof ProjectOpenQuestionsPage> = {
  title: "Modules/ContextStrategy/ProjectOpenQuestionsPage",
  component: ProjectOpenQuestionsPage,
  decorators: [
    withRouter(`/projects/${PROJECT_ID}/modules/context_strategy/open-questions`, "/projects/:projectId/modules/context_strategy/open-questions"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectOpenQuestionsPage>;

export const ListsOpenQuestions: Story = {
  beforeEach: () => mockPageApis([
    openQuestion(),
    openQuestion({ id: "open-question-2", question: "Is the UI presentation question still open?", status: "withdrawn" }),
  ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Should we standardise on a single battery vendor?")).toBeInTheDocument());
    await expect(canvas.getByText("Is the UI presentation question still open?")).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockPageApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No Open Questions recorded for this project yet.")).toBeInTheDocument());
  },
};

export const OpenCreateModal: Story = {
  beforeEach: () => mockPageApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New Open Question" }));
    await userEvent.click(canvas.getByRole("button", { name: "New Open Question" }));
    // `OpenQuestionFormModal` portals to `document.body`.
    await expect(within(document.body).getByRole("heading", { name: "New Open Question" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ListsOpenQuestions };
export const DarkTheme: Story = { ...ListsOpenQuestions, globals: { theme: "dark" } };
