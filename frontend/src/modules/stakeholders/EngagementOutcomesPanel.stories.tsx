import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { MemoryRouter } from "react-router-dom";

import { withToast } from "../../testing/storybook-helpers";
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
    (Story) => (
      <MemoryRouter>
        <Story />
      </MemoryRouter>
    ),
  ],
  args: {
    projectId: "project-1", holderId: "engagement-1", api: build(),
    loadTargets: fn(async (targetType: string) => TARGETS[targetType] ?? []),
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
    await waitFor(() => canvas.getByRole("combobox", { name: "Outcome record" }));
    // The already-raised Pain Point is not offered again.
    await waitFor(() => expect(canvas.getByRole("option", { name: "Manual re-keying" })).toBeInTheDocument());
    await expect(canvas.queryByRole("option", { name: "Reports arrive late" })).not.toBeInTheDocument();
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Outcome record" }), "pp-2");
    await userEvent.click(canvas.getByRole("button", { name: "Add outcome" }));
    await waitFor(() => expect(args.api.add).toHaveBeenCalledWith("project-1", "engagement-1", "raised", "pain_point", "pp-2"));
    await waitFor(() => expect(within(document.body).getByText("Outcome recorded.")).toBeInTheDocument());
  },
};

/** Only an Open Question can be answered, so choosing "Answered" narrows the type picker to it. */
export const AnsweredOffersOnlyOpenQuestions: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("combobox", { name: "Outcome kind" }));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Outcome kind" }), "answered");
    const type = canvas.getByRole("combobox", { name: "Outcome type" });
    await expect(type).toHaveValue("open_question");
    await expect(within(type).queryByRole("option", { name: "Pain Point" })).not.toBeInTheDocument();
    await waitFor(() => expect(canvas.getByRole("option", { name: "Who signs off?" })).toBeInTheDocument());
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
