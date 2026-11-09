import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import {
  buildComponent, buildComponentPhases, buildComponentTrack, buildPhasePlan, buildPhasePlans, buildStage, buildStageWorkflow,
  buildUser, withStatefulAuth, withToast,
} from "../testing/storybook-helpers";
import { PhaseSchedulePanel } from "./PhaseSchedulePanel";

const COMPONENT = buildComponent({ id: "component-1", name: "Software" });
const STAGE = buildStage({ id: "stage-1", name: "Release 1", phase_id: "phase-review", phase_name: "Review", phase_kind: "review" });

/** Replies to the five reads the panel makes. */
function mockReads(plans: ReturnType<typeof buildPhasePlans>, tracks = buildComponentPhases({ mode: "off", own_mode: "off", tracks: [] })) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/phase-plans")) return plans;
    if (path.endsWith("/component-stages")) return tracks;
    if (path.endsWith("/stages")) return [STAGE];
    if (path.endsWith("/components")) return [COMPONENT];
    return [buildStageWorkflow()];
  });
}

/** The project's phase schedule: reminder lead time, a stage owner and the expected and actual dates of each phase. */
const meta: Meta<typeof PhaseSchedulePanel> = {
  title: "Components/PhaseSchedulePanel",
  component: PhaseSchedulePanel,
  decorators: [withToast(), withStatefulAuth(buildUser({ ui_preferences: {} }))],
  args: { projectId: "project-1", organizationId: "org-1", orgUsers: [] },
};
export default meta;

type Story = StoryObj<typeof PhaseSchedulePanel>;

/** An unscheduled phase says so, the current phase is badged, and the inherited lead time is named. */
export const ShowsPhasesAndTheCurrentOne: Story = {
  beforeEach: () => mockReads(buildPhasePlans()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Current")).toBeInTheDocument();
    await expect(canvas.getAllByText("Not scheduled")).toHaveLength(5);
    await expect(canvas.getByText(/Following the parent project: 7 days/)).toBeInTheDocument();
  },
};

/** The current phase past its expected end is marked overdue; a completed one shows how late it finished. */
export const OverdueAndCompletedPhases: Story = {
  beforeEach: () => mockReads(buildPhasePlans({
    plans: [
      buildPhasePlan({ phase_id: "phase-review", expected_from: "2020-01-01", expected_to: "2020-01-10", started_at: "2020-01-02T09:00:00Z" }),
      buildPhasePlan({
        phase_id: "phase-scoping", expected_from: "2019-12-01", expected_to: "2019-12-10", started_at: "2019-12-01T09:00:00Z",
        completed_at: "2019-12-12T12:00:00Z",
      }),
    ],
  })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Overdue")).toBeInTheDocument();
    await expect(canvas.getByText(/2 days late/)).toBeInTheDocument();
  },
};

/** Changing the lead time saves it; a null follows the parent project. */
export const LeadTimeSaves: Story = {
  beforeEach: () => {
    mockReads(buildPhasePlans());
    spyOn(api, "put").mockResolvedValue({});
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: /Reminder lead time/ }), "14");
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/v1/projects/project-1/phase-reminder-settings", { lead_days: 14 }));
  },
};

/** Editing a phase saves its range for the stage itself (no component). */
export const EditingAPhaseSavesItsRange: Story = {
  beforeEach: () => {
    mockReads(buildPhasePlans());
    spyOn(api, "put").mockResolvedValue({});
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Schedule phase Review" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.type(dialog.getByLabelText("Expected start"), "2026-12-01");
    await userEvent.type(dialog.getByLabelText("Expected end"), "2026-12-10");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/v1/projects/project-1/stages/stage-1/phase-plan", {
      phase_id: "phase-review", component_id: null, expected_from: "2026-12-01", expected_to: "2026-12-10",
    }));
  },
};

/** With component phases on, a component can be chosen and its own track's phases are scheduled. */
export const ComponentScopeSchedulesTheTrack: Story = {
  beforeEach: () => {
    mockReads(buildPhasePlans(), buildComponentPhases({ tracks: [buildComponentTrack({ stage_id: "stage-1" })] }));
    spyOn(api, "put").mockResolvedValue({});
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: /Schedule of/ }), "component-1");
    await userEvent.click(canvas.getByRole("button", { name: "Schedule phase Scoping" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.type(dialog.getByLabelText("Expected end"), "2026-12-10");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/v1/projects/project-1/stages/stage-1/phase-plan", {
      phase_id: "phase-scoping", component_id: "component-1", expected_from: null, expected_to: "2026-12-10",
    }));
  },
};
