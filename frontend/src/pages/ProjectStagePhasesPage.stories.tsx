import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import {
  buildComponent, buildComponentPhases, buildComponentTrack, buildStage, buildStageWorkflow, withRouter, withToast,
} from "../testing/storybook-helpers";
import { ProjectStagePhasesPage } from "./ProjectStagePhasesPage";

const STAGE = buildStage({ id: "s1", name: "Design" });
const SOFTWARE = buildComponent({ id: "c1", name: "Software" });

function mockReads(phases: ReturnType<typeof buildComponentPhases>) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/component-stages")) return phases;
    if (path.endsWith("/stages")) return [STAGE];
    if (path.endsWith("/components")) return [SOFTWARE];
    return [buildStageWorkflow()];
  });
}

/** The stages' phases, and the component tracks a person may move, outside project administration. */
const meta: Meta<typeof ProjectStagePhasesPage> = {
  title: "Pages/ProjectStagePhasesPage",
  component: ProjectStagePhasesPage,
  decorators: [withRouter("/projects/project-1/stage-phases", "/projects/:projectId/stage-phases"), withToast()],
};
export default meta;

type Story = StoryObj<typeof ProjectStagePhasesPage>;

/** Stages are listed read only with their phase and workflow. */
export const ListsStagesWithTheirPhase: Story = {
  beforeEach: () => mockReads(buildComponentPhases({ mode: "off", own_mode: "off", tracks: [] })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Design")).toBeInTheDocument();
    await expect(canvas.getByText("Scoping · Open")).toBeInTheDocument();
    await expect(canvas.getByText(/Component phases are off/)).toBeInTheDocument();
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
