import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { buildComponentTrack, buildPhasePlan, buildStageWorkflow } from "../testing/storybook-helpers";
import { trackRows } from "../utils/deliveryPlan";
import { DeliveryTimeline } from "./DeliveryTimeline";

const TODAY = "2026-11-09";
const WORKFLOW = buildStageWorkflow();
const plans = [
  buildPhasePlan({
    stage_id: "s1", component_id: "c1", phase_id: "phase-scoping", expected_from: "2026-10-01", expected_to: "2026-10-31",
    started_at: "2026-10-02T12:00:00Z",
  }),
  buildPhasePlan({ stage_id: "s1", component_id: "c2", phase_id: "phase-review", expected_from: "2026-11-01", expected_to: "2026-12-15", started_at: "2026-11-03T00:00:00Z" }),
];
const rows = trackRows([
  buildComponentTrack({ component_id: "c1", stage_id: "s1" }),
  buildComponentTrack({ component_id: "c2", stage_id: "s1", phase_id: "phase-review", phase_name: "Review", phase_kind: "review" }),
  buildComponentTrack({ component_id: "c3", stage_id: "s1" }),
  buildComponentTrack({ component_id: "c4", stage_id: "s1", not_applicable: true }),
], [WORKFLOW], plans, TODAY);

const items = [
  { row: rows[0], title: "Software", subtitle: "Release 1" },
  { row: rows[1], title: "Hardware", subtitle: "Release 1" },
  { row: rows[2], title: "Firmware", subtitle: "Release 1" },
  { row: rows[3], title: "Packaging", subtitle: "Release 1" },
];

/** Bars on a shared date axis with today marked; the table beside it is the accessible alternative. */
const meta: Meta<typeof DeliveryTimeline> = {
  title: "Components/DeliveryTimeline",
  component: DeliveryTimeline,
  args: { items, today: TODAY },
};
export default meta;

type Story = StoryObj<typeof DeliveryTimeline>;

/** Every row is named in words for assistive technology, an overdue row says so in text, and a row without dates says so rather than inventing a bar. */
export const RowsAreNamedInWords: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByRole("listitem")).toHaveLength(4);
    await expect(canvas.getByText(/Software in Release 1: Scoping, Step 1 of 5, expected .*, overdue\./)).toBeInTheDocument();
    await expect(canvas.getByText(/Hardware in Release 1: Review, Step 2 of 5, expected .*\./)).toBeInTheDocument();
    await expect(canvas.getByText("Overdue")).toBeInTheDocument();
    await expect(canvas.getByText("No dates set")).toBeInTheDocument();
    await expect(canvas.getByText("Not applicable")).toBeInTheDocument();
    await expect(canvas.getByText("Today")).toBeInTheDocument();
  },
};

/** With no dates on any row the chart says there is nothing to draw. */
export const NoDatesAnywhere: Story = {
  args: { items: items.slice(2, 3) },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText(/nothing to draw/)).toBeInTheDocument();
  },
};
