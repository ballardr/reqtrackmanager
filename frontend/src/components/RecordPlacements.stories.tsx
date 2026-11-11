import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import {
  buildPlace, buildPlacementsApi, buildRecordPlacements, openPlacementPicker, PLACEMENTS_PROJECT_ID,
} from "../testing/placementsFixtures";
import { RecordPlacements } from "./RecordPlacements";

/**
 * The components of one existing record, in its header: chips for everyone, and the picker for someone who may place
 * the record. A change is saved at once and put back with an error toast if refused.
 */
const meta: Meta<typeof RecordPlacements> = {
  title: "Components/RecordPlacements",
  component: RecordPlacements,
  args: { projectId: PLACEMENTS_PROJECT_ID, artefactType: "pain_point", artefactId: "record-1" },
};
export default meta;

type Story = StoryObj<typeof RecordPlacements>;

export const AddingAndRemovingAPlace: Story = {
  args: { api: buildPlacementsApi(), onChanged: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(await within(await canvas.findByRole("group", { name: "Components" })).findByText("Hardware / Cooling")).toBeInTheDocument();
    await openPlacementPicker(canvas);
    await userEvent.click(await within(document.body).findByRole("checkbox", { name: "Software" }));
    await waitFor(() => expect(args.api!.set).toHaveBeenCalledWith(PLACEMENTS_PROJECT_ID, "pain_point", "record-1", [
      { component_id: "c-hw", category_id: "k-cool" },
      { component_id: "c-sw", category_id: null },
    ]));
    await expect(args.onChanged).toHaveBeenCalled();
    await userEvent.click(await canvas.findByRole("button", { name: "Remove Hardware / Cooling" }));
    await waitFor(() => expect(args.api!.set).toHaveBeenLastCalledWith(PLACEMENTS_PROJECT_ID, "pain_point", "record-1", [
      { component_id: "c-sw", category_id: null },
    ]));
  },
};

export const ReadOnlyChipsForSomeoneWhoCannotPlace: Story = {
  args: {
    api: buildPlacementsApi(buildRecordPlacements({ can_edit: false, placements: [buildPlace("c-hw"), buildPlace("c-sw")] })),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Hardware")).toBeInTheDocument();
    await expect(canvas.getByText("Software")).toBeInTheDocument();
    await expect(canvas.queryByRole("button")).not.toBeInTheDocument();
  },
};

export const ARefusedChangeIsPutBack: Story = {
  args: { api: buildPlacementsApi(undefined, { set: fn(async () => { throw new Error("Refused."); }) }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Remove Hardware / Cooling" }));
    await expect(await within(await canvas.findByRole("group", { name: "Components" })).findByText("Hardware / Cooling")).toBeInTheDocument();
  },
};

export const NothingForARecordThatKeepsItsOwnComponent: Story = {
  args: { api: buildPlacementsApi(buildRecordPlacements({ can_edit: false, managed_on_record: true })), artefactType: "requirement" },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.get).toHaveBeenCalled());
    await expect(within(canvasElement).queryByText("Hardware / Cooling")).not.toBeInTheDocument();
  },
};

export const NothingWhenNotPlacedAndNotAllowedToPlace: Story = {
  args: { api: buildPlacementsApi(buildRecordPlacements({ can_edit: false, placements: [] })) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.get).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("group")).not.toBeInTheDocument();
  },
};
