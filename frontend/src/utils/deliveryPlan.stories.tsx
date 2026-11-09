import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { buildComponentTrack, buildPhasePlan, buildStage, buildStageWorkflow } from "../testing/storybook-helpers";
import { dayNumber, stageRows, timelineBounds, trackRows } from "./deliveryPlan";

const WORKFLOW = buildStageWorkflow();

/** Pure-function checks for the delivery plan rows (progress, expected range, overdue, bounds), run as stories like the other helpers. */
const meta: Meta = { title: "Utils/DeliveryPlan" };
export default meta;

type Story = StoryObj;

/** A track in the second of five phases has completed one phase; a closed phase counts the whole workflow. */
export const ProgressCountsCompletedPhases: Story = {
  render: () => <div>Progress</div>,
  play: async () => {
    const [review, done] = trackRows([
      buildComponentTrack({ component_id: "c1", phase_id: "phase-review", phase_name: "Review", phase_kind: "review" }),
      buildComponentTrack({ component_id: "c2", phase_id: "phase-completed", phase_name: "Completed", phase_kind: "closed" }),
    ], [WORKFLOW], [], "2026-11-09");
    await expect([review.completedPhases, review.totalPhases, review.progress]).toEqual([1, 5, 0.2]);
    await expect([done.completedPhases, done.progress, done.completed]).toEqual([5, 1, true]);
  },
};

/** The expected range spans the holder's own plan rows only; nothing is inferred for one without dates. */
export const ExpectedRangeIsTheSpanOfTheHoldersOwnRows: Story = {
  render: () => <div>Range</div>,
  play: async () => {
    const plans = [
      buildPhasePlan({ stage_id: "s1", component_id: "c1", phase_id: "phase-scoping", expected_from: "2026-12-01", expected_to: "2026-12-10" }),
      buildPhasePlan({ stage_id: "s1", component_id: "c1", phase_id: "phase-review", expected_from: "2026-12-11", expected_to: "2026-12-20" }),
      buildPhasePlan({ stage_id: "s1", component_id: "c2", phase_id: "phase-scoping", expected_from: "2027-01-01", expected_to: "2027-01-05" }),
      buildPhasePlan({ stage_id: "s1", component_id: null, phase_id: "phase-scoping", expected_from: "2026-11-01", expected_to: "2026-11-05" }),
    ];
    const [one, two, three] = trackRows([
      buildComponentTrack({ component_id: "c1", stage_id: "s1" }),
      buildComponentTrack({ component_id: "c2", stage_id: "s1" }),
      buildComponentTrack({ component_id: "c3", stage_id: "s1" }),
    ], [WORKFLOW], plans, "2026-11-09");
    await expect([one.expectedFrom, one.expectedTo]).toEqual(["2026-12-01", "2026-12-20"]);
    await expect([two.expectedFrom, two.expectedTo]).toEqual(["2027-01-01", "2027-01-05"]);
    await expect([three.expectedFrom, three.expectedTo]).toEqual([null, null]);
    const [stage] = stageRows([buildStage({ id: "s1" })], [WORKFLOW], plans, true, "2026-11-09");
    await expect([stage.expectedFrom, stage.expectedTo]).toEqual(["2026-11-01", "2026-11-05"]);
  },
};

/** Overdue is the current phase's own end before the viewer's day: the end day itself is not yet overdue, and a closed phase never is. */
export const OverdueUsesTheViewersDayAtTheBoundary: Story = {
  render: () => <div>Overdue</div>,
  play: async () => {
    const plans = [buildPhasePlan({ stage_id: "s1", component_id: "c1", phase_id: "phase-scoping", expected_from: "2026-11-01", expected_to: "2026-11-09" })];
    const track = buildComponentTrack({ component_id: "c1", stage_id: "s1" });
    await expect(trackRows([track], [WORKFLOW], plans, "2026-11-09")[0].overdue).toBe(false);
    await expect(trackRows([track], [WORKFLOW], plans, "2026-11-10")[0].overdue).toBe(true);
    const closed = buildComponentTrack({ component_id: "c1", stage_id: "s1", phase_id: "phase-completed", phase_kind: "closed" });
    await expect(trackRows([closed], [WORKFLOW], plans, "2026-11-10")[0].overdue).toBe(false);
    const notApplicable = buildComponentTrack({ component_id: "c1", stage_id: "s1", not_applicable: true });
    await expect(trackRows([notApplicable], [WORKFLOW], plans, "2026-11-10")[0].overdue).toBe(false);
  },
};

/** The axis covers every date and today, padded; with no dates at all there is nothing to draw. */
export const BoundsCoverDatesAndToday: Story = {
  render: () => <div>Bounds</div>,
  play: async () => {
    const plans = [buildPhasePlan({ stage_id: "s1", component_id: "c1", phase_id: "phase-scoping", expected_from: "2026-12-01", expected_to: "2026-12-31" })];
    const rows = trackRows([buildComponentTrack({ component_id: "c1", stage_id: "s1" })], [WORKFLOW], plans, "2026-11-09");
    const bounds = timelineBounds(rows, "2026-11-09");
    await expect(bounds).not.toBeNull();
    await expect(bounds?.from).toBeLessThan(dayNumber("2026-11-09"));
    await expect(bounds?.to).toBeGreaterThan(dayNumber("2026-12-31"));
    const none = trackRows([buildComponentTrack({ component_id: "c1", stage_id: "s1" })], [WORKFLOW], [], "2026-11-09");
    await expect(timelineBounds(none, "2026-11-09")).toBeNull();
  },
};
