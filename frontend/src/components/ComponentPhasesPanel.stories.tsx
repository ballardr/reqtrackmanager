import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import {
  buildComponent, buildComponentPhases, buildComponentTrack, buildStage, buildStageWorkflow, withToast,
} from "../testing/storybook-helpers";
import { ComponentPhasesPanel } from "./ComponentPhasesPanel";

const COMPONENT = buildComponent({ id: "component-1", name: "Software" });
const STAGE = buildStage({ id: "stage-1", name: "Release 1" });
const STAGE_TWO = buildStage({ id: "stage-2", name: "Release 2", sort_order: 1 });

/** Replies to the four reads the panel makes; `phases` is the component-phases state. */
function mockReads(phases: ReturnType<typeof buildComponentPhases>) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/component-stages")) return phases;
    if (path.endsWith("/stages")) return [STAGE, STAGE_TWO];
    if (path.endsWith("/components")) return [COMPONENT];
    return [buildStageWorkflow()];
  });
}

/** Component phases: a project switch, and per component a track per stage with a phase picker. */
const meta: Meta<typeof ComponentPhasesPanel> = {
  title: "Components/ComponentPhasesPanel",
  component: ComponentPhasesPanel,
  decorators: [withToast()],
  args: { projectId: "project-1", organizationId: "org-1", orgUsers: [] },
};
export default meta;

type Story = StoryObj<typeof ComponentPhasesPanel>;

/** With the switch off nothing per component is shown and the stage phase is said to apply. */
export const OffShowsOnlyTheSwitch: Story = {
  beforeEach: () => mockReads(buildComponentPhases({ mode: "off", own_mode: "off", tracks: [] })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText(/Component phases are off/)).toBeInTheDocument();
    await expect(canvas.queryByRole("combobox", { name: /Phase of/ })).not.toBeInTheDocument();
  },
};

/** Changing the switch saves it (a null mode follows the parent project). */
export const SwitchSavesTheMode: Story = {
  beforeEach: () => {
    mockReads(buildComponentPhases({ mode: "off", own_mode: "off", tracks: [] }));
    spyOn(api, "put").mockResolvedValue({});
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: /Component phases/ }), "on");
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/v1/projects/project-1/component-phases-settings", { mode: "on" }));
  },
};

/** Inherited setting is named. */
export const InheritedModeIsNamed: Story = {
  beforeEach: () => mockReads(buildComponentPhases({ own_mode: null, inherited: true, tracks: [] })),
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText(/Following the parent project: On/)).toBeInTheDocument();
  },
};

/** Moving a track posts the phase; the advisory badge shows once the previous stage has closed. */
export const TrackMovesAndShowsAdvisoryBadge: Story = {
  beforeEach: () => {
    mockReads(buildComponentPhases({
      tracks: [
        buildComponentTrack({ stage_id: "stage-1", phase_id: "phase-completed", phase_name: "Completed", phase_kind: "closed" }),
        buildComponentTrack({ stage_id: "stage-2", previous_closed: true }),
      ],
    }));
    spyOn(api, "post").mockResolvedValue({});
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Previous stage closed")).toBeInTheDocument();
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Phase of Software in Release 2" }), "phase-review");
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        "/api/v1/projects/project-1/components/component-1/stages/stage-2/transition",
        { phase_id: "phase-review", cascade_to_requirements: false },
      ),
    );
  },
};

/** A closed phase asks whether to complete the component's approved requirements too. */
export const ClosingAsksAboutRequirements: Story = {
  beforeEach: () => {
    mockReads(buildComponentPhases({ tracks: [buildComponentTrack({ stage_id: "stage-1" }), buildComponentTrack({ stage_id: "stage-2" })] }));
    spyOn(api, "post").mockResolvedValue({});
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Phase of Software in Release 1" }), "phase-completed");
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.click(dialog.getByRole("checkbox"));
    await userEvent.click(dialog.getByRole("button", { name: "Completed" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        "/api/v1/projects/project-1/components/component-1/stages/stage-1/transition",
        { phase_id: "phase-completed", cascade_to_requirements: true },
      ),
    );
  },
};

/** A track the caller cannot move is read-only, and a not applicable stage shows no picker. */
export const ReadOnlyAndNotApplicable: Story = {
  beforeEach: () =>
    mockReads(buildComponentPhases({
      tracks: [buildComponentTrack({ stage_id: "stage-1", can_move: false }), buildComponentTrack({ stage_id: "stage-2", not_applicable: true })],
    })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("combobox", { name: "Phase of Software in Release 1" })).toBeDisabled();
    await expect(canvas.getByText("Not applicable")).toBeInTheDocument();
    await expect(canvas.queryByRole("combobox", { name: "Phase of Software in Release 2" })).not.toBeInTheDocument();
  },
};

/** The edit dialog sends only what changed. */
export const EditSendsOnlyTheChanges: Story = {
  beforeEach: () => {
    mockReads(buildComponentPhases({ tracks: [buildComponentTrack({ stage_id: "stage-1" }), buildComponentTrack({ stage_id: "stage-2" })] }));
    spyOn(api, "patch").mockResolvedValue({});
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Edit Software in Release 1" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.click(dialog.getByRole("switch", { name: /Not applicable/ }));
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith("/api/v1/projects/project-1/components/component-1/stages/stage-1/track", { not_applicable: true }),
    );
  },
};
