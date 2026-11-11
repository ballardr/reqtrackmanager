import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import {
  buildComponent, buildComponentPhases, buildComponentTrack, buildPhasePlan, buildPhasePlans, buildStage, buildStageWorkflow, buildUser,
  withRouter, withStatefulAuth, withToast,
} from "../testing/storybook-helpers";
import { ProjectStagePhasesPage } from "./ProjectStagePhasesPage";

const STAGE = buildStage({ id: "s1", name: "Design", can_lock: true });
const SOFTWARE = buildComponent({ id: "c1", name: "Software" });

function mockReads(phases: ReturnType<typeof buildComponentPhases>, plans = buildPhasePlans()) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/component-stages")) return phases;
    if (path.endsWith("/phase-plans")) return plans;
    if (path.endsWith("/stages")) return [STAGE];
    if (path.endsWith("/components")) return [SOFTWARE];
    return [buildStageWorkflow()];
  });
}

/** The stages' phases, and the component tracks a person may move, outside project administration. */
const meta: Meta<typeof ProjectStagePhasesPage> = {
  title: "Pages/ProjectStagePhasesPage",
  component: ProjectStagePhasesPage,
  decorators: [
    withRouter("/projects/project-1/stage-phases", "/projects/:projectId/stage-phases"), withToast(),
    withStatefulAuth(buildUser({ ui_preferences: {} })),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectStagePhasesPage>;

/** Stages are listed with their phase; with component phases off there is no "By component" section. */
export const ListsStagesWithTheirPhase: Story = {
  beforeEach: () => mockReads(buildComponentPhases({ mode: "off", own_mode: "off", tracks: [] })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Design")).toBeInTheDocument();
    await expect(canvas.getByRole("combobox", { name: "Phase of Design" })).toHaveDisplayValue("Scoping");
    await expect(canvas.queryByRole("heading", { name: "By component" })).not.toBeInTheDocument();
  },
};

/** A track's owner (not a manager) moves their own track from here. */
export const AnOwnerMovesTheirTrack: Story = {
  beforeEach: () => {
    mockReads(buildComponentPhases({ tracks: [buildComponentTrack({ component_id: "c1", stage_id: "s1", can_move: true })] }));
    spyOn(api, "post").mockResolvedValue({});
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Phase of Software in Design" }), "Review");
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "/api/v1/projects/project-1/components/c1/stages/s1/transition", { phase_id: "phase-review", cascade_to_requirements: false },
    ));
  },
};

const SCHEDULED = buildPhasePlans({
  plans: [
    buildPhasePlan({ stage_id: "s1", component_id: null, phase_id: "phase-scoping", expected_from: "2020-01-01", expected_to: "2020-02-01" }),
    buildPhasePlan({ stage_id: "s1", component_id: "c1", phase_id: "phase-scoping", expected_from: "2020-01-01", expected_to: "2020-03-01" }),
  ],
});

/** Progress, the expected range and an overdue state show for the stage and for each track. */
export const ShowsProgressDatesAndOverdue: Story = {
  beforeEach: () => mockReads(buildComponentPhases({ tracks: [buildComponentTrack({ component_id: "c1", stage_id: "s1" })] }), SCHEDULED),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Status by stage" });
    await expect(canvas.getAllByText("Step 1 of 5")).toHaveLength(2);
    await expect(canvas.getAllByText("Overdue")).toHaveLength(2);
  },
};

/** The timeline is one choice of view, remembered per person; the table stays available. */
export const SwitchesToTheTimeline: Story = {
  beforeEach: () => mockReads(buildComponentPhases({ tracks: [buildComponentTrack({ component_id: "c1", stage_id: "s1" })] }), SCHEDULED),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Status by stage" });
    await userEvent.click(canvas.getByRole("button", { name: "Timeline view" }));
    await waitFor(() => expect(canvas.getAllByRole("list", { name: "Delivery timeline" })).toHaveLength(2));
    await userEvent.click(canvas.getByRole("button", { name: "Table view" }));
    await waitFor(() => expect(canvas.queryByRole("list", { name: "Delivery timeline" })).not.toBeInTheDocument());
  },
};

/** A manager sets the expected range of a stage's current phase from the page. */
export const AManagerSetsTheStageDates: Story = {
  beforeEach: () => {
    mockReads(buildComponentPhases({ mode: "off", own_mode: "off", tracks: [] }), SCHEDULED);
    spyOn(api, "put").mockResolvedValue({});
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Set expected dates for Design" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      "/api/v1/projects/project-1/stages/s1/phase-plan",
      { phase_id: "phase-scoping", component_id: null, expected_from: "2020-01-01", expected_to: "2020-02-01" },
    ));
  },
};

/** Without the manager role a stage cannot be moved or scheduled from the page. */
export const AMemberCannotScheduleAStage: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/component-stages")) return buildComponentPhases({ mode: "off", own_mode: "off", tracks: [] });
      if (path.endsWith("/phase-plans")) return SCHEDULED;
      if (path.endsWith("/stages")) return [buildStage({ id: "s1", name: "Design", can_lock: false })];
      if (path.endsWith("/components")) return [SOFTWARE];
      return [buildStageWorkflow()];
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("combobox", { name: "Phase of Design" })).toBeDisabled();
    await expect(canvas.queryByRole("button", { name: /Set expected dates/ })).not.toBeInTheDocument();
  },
};
