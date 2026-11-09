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

/** "Only tracks I can move" drops the rows the person may not move. */
export const OnlyTracksIMayMove: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("checkbox", { name: /Only tracks I can move/ }));
    await waitFor(() => expect(canvas.queryByText("Hardware")).not.toBeInTheDocument());
    await expect(canvas.getAllByText("Software")).toHaveLength(2);
  },
};

/** One flat row per component and stage, in component then stage order, with no disclosure. */
export const OneFlatRowPerComponentAndStage: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = canvas.getByRole("table");
    await expect(within(table).getAllByRole("row")).toHaveLength(5);
    await expect(canvas.queryByRole("button", { name: /Show or hide/ })).not.toBeInTheDocument();
    const columnHeaders = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    await expect(columnHeaders).toEqual(["Component", "Stage", "Phase", "Workflow", "Owner", "State"]);
  },
};

/** With every track filtered out the list says there is nothing to show. */
export const NoTracksMatchTheFilter: Story = {
  args: { state: buildComponentPhases({ tracks: [] }) },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText(/no components or stages yet/)).toBeInTheDocument();
  },
};

/** The edit column appears only where the host can edit a track. */
export const EditColumnNeedsOnEdit: Story = {
  args: { onEdit: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Edit Software in Release 1" }));
    await expect(args.onEdit).toHaveBeenCalled();
  },
};
