import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { expectHeaderSorts } from "../testing/sortHelpers";
import { buildPhasePlan, buildStage, buildStageWorkflow, withToast } from "../testing/storybook-helpers";
import { StagePlanTable } from "./StagePlanTable";

const DESIGN = buildStage({ id: "s1", name: "Design", can_lock: true });
const BUILD = buildStage({ id: "s2", name: "Build", sort_order: 1, can_lock: true });

/** The stages with phase, progress and expected range; a manager moves one in place. */
const meta: Meta<typeof StagePlanTable> = {
  title: "Components/StagePlanTable",
  component: StagePlanTable,
  decorators: [withToast()],
  args: {
    projectId: "project-1", stages: [DESIGN, BUILD], workflows: [buildStageWorkflow()], canManage: true, onChanged: fn(),
    plans: [buildPhasePlan({ stage_id: "s1", component_id: null, phase_id: "phase-scoping", expected_from: "2020-01-01", expected_to: "2020-02-01" })],
  },
};
export default meta;

type Story = StoryObj<typeof StagePlanTable>;

/** Progress, the expected range and an overdue badge (a past end) read in the table; a stage with no dates says so. */
export const ProgressDatesAndOverdue: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByText("Step 1 of 5")).toHaveLength(2);
    await expect(canvas.getByText("Overdue")).toBeInTheDocument();
    await expect(canvas.getByText("No dates set")).toBeInTheDocument();
  },
};

/** A manager moves a stage from the picker. */
export const AManagerMovesAStage: Story = {
  beforeEach: () => { spyOn(api, "post").mockResolvedValue({}); },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Phase of Design" }), "Review");
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "/api/v1/projects/project-1/stages/s1/transition", { phase_id: "phase-review", cascade_to_requirements: false },
    ));
    await waitFor(() => expect(args.onChanged).toHaveBeenCalled());
  },
};

/** Without the manager role the picker is unavailable and no schedule button is offered. */
export const ReadOnlyForAMember: Story = {
  args: { canManage: false, stages: [buildStage({ id: "s1", name: "Design", can_lock: false })] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("combobox", { name: "Phase of Design" })).toBeDisabled();
    await expect(canvas.queryByRole("button", { name: /Set expected dates/ })).not.toBeInTheDocument();
  },
};

/** The schedule button opens the host's editor for the stage. */
export const ScheduleButtonCallsTheHost: Story = {
  args: { onSchedule: fn() },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Set expected dates for Design" }));
    await expect(args.onSchedule).toHaveBeenCalledWith(expect.objectContaining({ id: "s1" }));
  },
};

/** The timeline view draws the same rows as bars. */
export const TimelineView: Story = {
  args: { view: "timeline" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByRole("listitem")).toHaveLength(2);
    await expect(canvas.getByText("Overdue")).toBeInTheDocument();
  },
};

/** The Stage header orders the stages by name, ascending then descending (the default is the project's stage order). */
export const StageHeaderSortsTheStages: Story = {
  play: async ({ canvasElement }) => {
    const table = within(canvasElement).getByRole("table");
    await expectHeaderSorts(table, "Stage", ["Build", "Design"]);
  },
};