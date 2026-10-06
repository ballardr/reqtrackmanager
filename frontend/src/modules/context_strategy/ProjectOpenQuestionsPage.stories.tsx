import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildProject, withRouter, withToast } from "../../testing/storybook-helpers";
import { ProjectOpenQuestionsPage } from "./ProjectOpenQuestionsPage";
import type { OpenQuestion } from "./types";

const PROJECT_ID = "project-1";
const daysFromNow = (days: number) => new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);

function question(overrides: Partial<OpenQuestion> = {}): OpenQuestion {
  return {
    id: "oq-1", project_id: PROJECT_ID, creator_id: "user-1", is_archived: false, archived_at: null, archived_by: null,
    question: "Which regions are in scope?", context: "", evidence: "", priority: "high", status: "open",
    owner_id: null, due_date: null, is_locked: false, created_at: "2026-01-05T09:00:00Z", updated_at: "2026-01-05T09:00:00Z",
    ...overrides,
  };
}

function mockPageApis(questions: OpenQuestion[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/projects/${PROJECT_ID}`) return buildProject({ id: PROJECT_ID, organization_id: "org-1" });
    if (path.startsWith(`/api/v1/projects/${PROJECT_ID}/modules/context_strategy/open-questions`)) return questions;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const QUESTIONS = [
  question({ id: "overdue-unowned", question: "Overdue and unowned", due_date: daysFromNow(-12) }),
  question({ id: "overdue-owned", question: "Overdue but owned", due_date: daysFromNow(-3), owner_id: "user-2" }),
  question({ id: "future-unowned", question: "Due later, unowned", due_date: daysFromNow(20) }),
  question({ id: "resolved-overdue", question: "Resolved long ago", due_date: daysFromNow(-30), status: "resolved" }),
];

const meta: Meta<typeof ProjectOpenQuestionsPage> = {
  title: "Modules/ContextStrategy/ProjectOpenQuestionsPage",
  component: ProjectOpenQuestionsPage,
  decorators: [
    // `parameters.query` opens the page the way a report figure's link does (`?open=1&overdue=1`).
    (Story, context) =>
      withRouter(
        `/projects/${PROJECT_ID}/modules/context_strategy/open-questions${context.parameters.query ?? ""}`,
        "/projects/:projectId/modules/context_strategy/open-questions",
      )(Story, context),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectOpenQuestionsPage>;

export const ListsOpenQuestions: Story = {
  beforeEach: () => mockPageApis(QUESTIONS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Overdue and unowned")).toBeInTheDocument());
    await expect(canvas.getByText("Resolved long ago")).toBeInTheDocument();
  },
};

/** The report's "Overdue" figure: unresolved questions whose due date has passed. */
export const OpensOverdueFromAReportFigure: Story = {
  parameters: { query: "?open=1&overdue=1" },
  beforeEach: () => mockPageApis(QUESTIONS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Overdue and unowned")).toBeInTheDocument());
    await expect(canvas.getByText("Overdue but owned")).toBeInTheDocument();
    await expect(canvas.queryByText("Due later, unowned")).not.toBeInTheDocument();
    await expect(canvas.queryByText("Resolved long ago")).not.toBeInTheDocument(); // resolved is not "open"
    await expect(canvas.getByRole("checkbox", { name: "Overdue only" })).toBeChecked();
    await userEvent.click(canvas.getByRole("checkbox", { name: "Overdue only" }));
    await expect(canvas.getByText("Due later, unowned")).toBeInTheDocument();
  },
};

/** The report's "Unowned" figure. */
export const OpensUnownedFromAReportFigure: Story = {
  parameters: { query: "?open=1&unowned=1" },
  beforeEach: () => mockPageApis(QUESTIONS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Due later, unowned")).toBeInTheDocument());
    await expect(canvas.getByText("Overdue and unowned")).toBeInTheDocument();
    await expect(canvas.queryByText("Overdue but owned")).not.toBeInTheDocument();
    await expect(canvas.getByRole("checkbox", { name: "Unowned only" })).toBeChecked();
  },
};
