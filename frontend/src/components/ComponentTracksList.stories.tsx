import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import {
  buildComponent, buildComponentPhases, buildComponentTrack, buildStage, buildStageWorkflow, withToast,
} from "../testing/storybook-helpers";
import { ComponentTracksList } from "./ComponentTracksList";

const SOFTWARE = buildComponent({ id: "c1", name: "Software" });
const HARDWARE = buildComponent({ id: "c2", name: "Hardware", sort_order: 1 });
const RELEASE_1 = buildStage({ id: "s1", name: "Release 1" });
const RELEASE_2 = buildStage({ id: "s2", name: "Release 2", sort_order: 1 });

const tracks = [
  buildComponentTrack({ component_id: "c1", stage_id: "s1", can_move: true }),
  buildComponentTrack({ component_id: "c1", stage_id: "s2", can_move: true }),
  buildComponentTrack({ component_id: "c2", stage_id: "s1", can_move: false }),
  buildComponentTrack({ component_id: "c2", stage_id: "s2", can_move: false, not_applicable: true }),
];

/** The tracks of every component through the stages, with a picker each; shared by project administration and the Stage phases page. */
const meta: Meta<typeof ComponentTracksList> = {
  title: "Components/ComponentTracksList",
  component: ComponentTracksList,
  decorators: [withToast()],
  args: {
    projectId: "project-1", state: buildComponentPhases({ tracks }), stages: [RELEASE_1, RELEASE_2],
    components: [SOFTWARE, HARDWARE], workflows: [buildStageWorkflow()], onChanged: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof ComponentTracksList>;

/** A picker for every track, disabled where the person may not move it. */
export const PickersFollowWhoMayMove: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("combobox", { name: "Phase of Software in Release 1" })).toBeEnabled();
    await expect(canvas.getByRole("combobox", { name: "Phase of Hardware in Release 1" })).toBeDisabled();
    await expect(canvas.getByText("Not applicable")).toBeInTheDocument();
  },
};

/** Filtering to one stage keeps only its tracks. */
export const FilterByStage: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Stage" }), "Release 2");
    await expect(canvas.queryByRole("combobox", { name: "Phase of Software in Release 1" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("combobox", { name: "Phase of Software in Release 2" })).toBeInTheDocument();
  },
};

/** "Only tracks I can move" drops the components with nothing the person may move. */
export const OnlyTracksIMayMove: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("checkbox", { name: /Only tracks I can move/ }));
    await waitFor(() => expect(canvas.queryByText("Hardware")).not.toBeInTheDocument());
    await expect(canvas.getByText("Software")).toBeInTheDocument();
  },
};

/** A component's group collapses to a one-line summary of its phases. */
export const CollapsingSummarisesPhases: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Show or hide the tracks of Hardware" }));
    await expect(canvas.queryByRole("combobox", { name: "Phase of Hardware in Release 1" })).not.toBeInTheDocument();
    await expect(canvas.getByText(/Release 1: Scoping · Release 2: Not applicable/)).toBeInTheDocument();
  },
};
