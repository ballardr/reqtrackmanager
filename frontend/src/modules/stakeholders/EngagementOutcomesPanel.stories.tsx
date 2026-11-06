import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";
import { MemoryRouter } from "react-router-dom";

import { api } from "../../api/client";
import { buildUser, withStatefulAuth, withToast } from "../../testing/storybook-helpers";
import { EngagementOutcomesPanel } from "./EngagementOutcomesPanel";
import type { EngagementOutcome, OutcomeTarget } from "./types";

const OUTCOMES: EngagementOutcome[] = [
  { link_id: "o1", kind: "raised", target_type: "pain_point", target_id: "pp-1", label: "Reports arrive late" },
  { link_id: "o2", kind: "answered", target_type: "open_question", target_id: "oq-1", label: "Which regions first?" },
];

const TARGETS: Record<string, OutcomeTarget[]> = {
  pain_point: [{ id: "pp-1", label: "Reports arrive late", status: "active" }, { id: "pp-2", label: "Manual re-keying", status: "active" }],
  stakeholder_need: [{ id: "need-1", label: "Diagnose faults quickly", status: "active" }],
  open_question: [{ id: "oq-1", label: "Which regions first?", status: null }, { id: "oq-2", label: "Who signs off?", status: null }],
};

function build(overrides: Partial<{ list: EngagementOutcome[] }> = {}) {
  return {
    list: fn(async () => overrides.list ?? OUTCOMES),
    add: fn(async () => OUTCOMES[0]),
    remove: fn(async () => undefined),
  };
}

const meta: Meta<typeof EngagementOutcomesPanel> = {
  title: "Modules/Stakeholders/EngagementOutcomesPanel",
  component: EngagementOutcomesPanel,
  decorators: [
    withToast(),
    withStatefulAuth(buildUser()),
    (Story) => (
      <MemoryRouter>
        <Story />
      </MemoryRouter>
    ),
  ],
  args: {
    projectId: "project-1", holderType: "engagement", holderId: "engagement-1", api: build(),
    loadTargets: fn(async (targetType: string) => TARGETS[targetType] ?? []),
    loadCreatableTypes: fn(async () => [
      { type: "pain_point", can_create: false },
      { type: "stakeholder_need", can_create: true },
      { type: "open_question", can_create: false },
    ]),
  },
};
export default meta;

type Story = StoryObj<typeof EngagementOutcomesPanel>;

export const ListsOutcomesWithLabelledKindAndType: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/Raised · Pain Point:/)).toBeInTheDocument());
    await expect(canvas.getByText(/Answered · Open Question:/)).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Reports arrive late" })).toBeInTheDocument();
    // Raw enum values never reach the screen.
    await expect(canvas.queryByText(/pain_point|open_question/)).not.toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  args: { api: build({ list: [] }) },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("Nothing raised or answered yet.")).toBeInTheDocument());
  },
};

export const AddsARaisedPainPoint: Story = {
  args: { api: build() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Add to Raised and answered" }));
    await userEvent.click(canvas.getByRole("button", { name: "Add to Raised and answered" }));
    const modal = within(within(document.body).getByRole("dialog", { name: "Record an outcome" }));
    // The already-raised Pain Point is not offered again.
    await waitFor(() => expect(modal.getByRole("option", { name: "Manual re-keying" })).toBeInTheDocument());
    await expect(modal.queryByRole("option", { name: "Reports arrive late" })).not.toBeInTheDocument();
    await userEvent.selectOptions(modal.getByRole("combobox", { name: "Outcome record" }), "pp-2");
    await userEvent.click(modal.getByRole("button", { name: "Add outcome" }));
    await waitFor(() => expect(args.api.add).toHaveBeenCalledWith("project-1", "engagement-1", "raised", "pain_point", "pp-2"));
    await waitFor(() => expect(within(document.body).getByText("Outcome recorded.")).toBeInTheDocument());
  },
};

/** Only an Open Question can be answered, so choosing "Answered" narrows the type picker to it. */
export const AnsweredOffersOnlyOpenQuestions: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Add to Raised and answered" }));
    await userEvent.click(canvas.getByRole("button", { name: "Add to Raised and answered" }));
    const modal = within(within(document.body).getByRole("dialog", { name: "Record an outcome" }));
    await userEvent.selectOptions(modal.getByRole("combobox", { name: "Outcome kind" }), "answered");
    const type = modal.getByRole("combobox", { name: "Outcome type" });
    await expect(type).toHaveValue("open_question");
    await expect(within(type).queryByRole("option", { name: "Pain Point" })).not.toBeInTheDocument();
    await waitFor(() => expect(modal.getByRole("option", { name: "Who signs off?" })).toBeInTheDocument());
  },
};

/** "Create new" is offered only for a type the server says the caller may create. */
export const OffersCreateNewOnlyForACreatableType: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Add to Raised and answered" }));
    await userEvent.click(canvas.getByRole("button", { name: "Add to Raised and answered" }));
    const modal = within(within(document.body).getByRole("dialog", { name: "Record an outcome" }));
    // Pain Point is the starting type and is not creatable by this person.
    await expect(modal.queryByRole("button", { name: /^Create new/ })).not.toBeInTheDocument();
    await userEvent.selectOptions(modal.getByRole("combobox", { name: "Outcome type" }), "stakeholder_need");
    await expect(modal.getByRole("button", { name: "Create new Stakeholder Need" })).toBeInTheDocument();
  },
};

/** The new record's own create dialog opens; once it reports the id the outcome is recorded in the same flow. */
export const CreatesARecordAndRecordsTheOutcome: Story = {
  args: { api: build() },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/tags")) return { names: [], suggestions: [], restricted: false, can_edit: true } as never;
      return [] as never;
    });
    spyOn(api, "post").mockImplementation(async () => ({ id: "need-new", name: "Faster triage" }) as never);
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Add to Raised and answered" }));
    await userEvent.click(canvas.getByRole("button", { name: "Add to Raised and answered" }));
    const outcome = within(within(document.body).getByRole("dialog", { name: "Record an outcome" }));
    await userEvent.selectOptions(outcome.getByRole("combobox", { name: "Outcome type" }), "stakeholder_need");
    await userEvent.click(outcome.getByRole("button", { name: "Create new Stakeholder Need" }));
    const form = within(await within(document.body).findByRole("dialog", { name: "New Stakeholder Need" }));
    await userEvent.type(form.getByLabelText("Need name"), "Faster triage");
    await userEvent.click(form.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.api.add).toHaveBeenCalledWith("project-1", "engagement-1", "raised", "stakeholder_need", "need-new"));
    await waitFor(() => expect(within(document.body).getByText("Outcome recorded.")).toBeInTheDocument());
  },
};

export const RemovesBehindAConfirm: Story = {
  args: { api: build() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Remove Reports arrive late" }));
    await userEvent.click(canvas.getByRole("button", { name: "Remove Reports arrive late" }));
    await userEvent.click(within(within(document.body).getByRole("dialog", { name: "Remove Reports arrive late?" })).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(args.api.remove).toHaveBeenCalledWith("project-1", "engagement-1", "o1"));
  },
};

export const DarkTheme: Story = { ...ListsOutcomesWithLabelledKindAndType, globals: { theme: "dark" } };
