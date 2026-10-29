import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildRecordColumns } from "../../testing/recordTablesFixtures";
import { buildProject, withRouter, withToast } from "../../testing/storybook-helpers";
import { ProjectOpenQuestionsPage } from "./ProjectOpenQuestionsPage";
import type { OpenQuestion } from "./types";
import { openListMenu, chooseExport } from "../../testing/listActionsMenu";

const PROJECT_ID = "project-1";
const daysFromNow = (days: number) => new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);

function question(overrides: Partial<OpenQuestion> = {}): OpenQuestion {
  return {
    id: "oq-1", project_id: PROJECT_ID, unique_code: "OQ-001", creator_id: "user-1", is_archived: false, archived_at: null, archived_by: null,
    question: "Which regions are in scope?", context: "", evidence: "", priority: "high", status: "open",
    owner: null, due_date: null, is_locked: false, created_at: "2026-01-05T09:00:00Z", updated_at: "2026-01-05T09:00:00Z",
    ...overrides,
  };
}

function mockPageApis(questions: OpenQuestion[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/records/open_question/columns")) return buildRecordColumns({ label: "Open questions" });
    if (path === `/api/v1/projects/${PROJECT_ID}`) return buildProject({ id: PROJECT_ID, organization_id: "org-1" });
    if (path.startsWith(`/api/v1/projects/${PROJECT_ID}/modules/context_strategy/open-questions`)) return questions;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const QUESTIONS = [
  question({ id: "overdue-unowned", question: "Overdue and unowned", due_date: daysFromNow(-12) }),
  question({ id: "overdue-owned", question: "Overdue but owned", due_date: daysFromNow(-3), owner: { type: "user", id: "user-2", label: "Jamie Lee", member_count: null, exists: true } }),
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
  parameters: { query: "?open=0" },
  beforeEach: () => mockPageApis(QUESTIONS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Overdue and unowned")).toBeInTheDocument());
    await expect(canvas.getByText("Resolved long ago")).toBeInTheDocument();
    await expect(canvas.getByRole("columnheader", { name: "Code" })).toBeInTheDocument();
    await expect(canvas.getAllByText(/OQ-\d{3}/).length).toBeGreaterThan(0);
  },
};

/** The list opens on unresolved questions only, with the filter shown ticked. */
export const OpensOnOpenQuestionsByDefault: Story = {
  beforeEach: () => mockPageApis(QUESTIONS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Overdue and unowned")).toBeInTheDocument());
    await expect(canvas.queryByText("Resolved long ago")).not.toBeInTheDocument();
    const openOnly = canvas.getByRole("checkbox", { name: "Open only" });
    await expect(openOnly).toBeChecked();
    await userEvent.click(openOnly);
    await expect(await canvas.findByText("Resolved long ago")).toBeInTheDocument();
  },
};

/** Open, investigating and ready for decision are open; resolved and withdrawn are not. */
export const OpenStatusesAreTheUnresolvedOnes: Story = {
  beforeEach: () => mockPageApis(
    (["open", "investigating", "ready_for_decision", "resolved", "withdrawn"] as const)
      .map((status, i) => question({ id: `q-${i}`, unique_code: `OQ-00${i + 1}`, question: `Question ${status}`, status })),
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Question open")).toBeInTheDocument());
    await expect(canvas.getByText("Question investigating")).toBeInTheDocument();
    await expect(canvas.getByText("Question ready_for_decision")).toBeInTheDocument();
    await expect(canvas.queryByText("Question resolved")).not.toBeInTheDocument();
    await expect(canvas.queryByText("Question withdrawn")).not.toBeInTheDocument();
  },
};

/** A link that names a status shows that slice, so the default never produces an empty list. */
export const AStatusLinkStartsWithOpenOnlyOff: Story = {
  parameters: { query: "?status=resolved" },
  beforeEach: () => mockPageApis(QUESTIONS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Resolved long ago")).toBeInTheDocument());
    await expect(canvas.queryByText("Overdue and unowned")).not.toBeInTheDocument();
    await expect(canvas.getByRole("checkbox", { name: "Open only" })).not.toBeChecked();
  },
};

/** When only the default hides everything, the empty state says why. */
export const EmptyBecauseOfOpenOnlySaysSo: Story = {
  beforeEach: () => mockPageApis([question({ status: "resolved" })]),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText(/^No open Open Questions\. Untick Open only/)).toBeInTheDocument());
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

/** Export and Import are on the title row; Export carries the page's filters (the server applies the same rules). */
export const ExportCarriesThePageFilters: Story = {
  beforeEach: () => {
    mockPageApis(QUESTIONS);
    spyOn(api, "getForBlob").mockResolvedValue(new Blob(["code\n"], { type: "text/csv" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Overdue and unowned")).toBeInTheDocument());
    await expect((await openListMenu(canvas)).getByRole("menuitem", { name: "Import from CSV" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await chooseExport(canvas, "CSV");
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith("/api/v1/projects/project-1/records/open_question/export?open_only=true"));
  },
};
