import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { DRAFT_ARTEFACT_ID } from "../api/artefactLinks";
import { buildPlacementsApi, buildRecordPlacements, openPlacementPicker, PLACEMENTS_PROJECT_ID } from "../testing/placementsFixtures";
import { ComponentField } from "./ComponentField";
import { takePendingPlacements } from "../hooks/pendingPlacements";

/**
 * The "Components" field of a create form. It asks about a record that does not exist yet, holds the choice for
 * `useCommitTags` to apply once the record is saved, and shows nothing when the caller may not place this kind of
 * record, the project has no components or the read fails.
 */
const meta: Meta<typeof ComponentField> = {
  title: "Components/ComponentField",
  component: ComponentField,
  args: { projectId: PLACEMENTS_PROJECT_ID, artefactType: "pain_point" },
};
export default meta;

type Story = StoryObj<typeof ComponentField>;

export const ChoosingComponentsForANewRecord: Story = {
  args: { api: buildPlacementsApi(buildRecordPlacements({ placements: [] })) },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await openPlacementPicker(canvas);
    await userEvent.click(await within(document.body).findByRole("checkbox", { name: "Hardware / Cooling" }));
    await userEvent.click(await within(document.body).findByRole("checkbox", { name: "Software" }));
    await expect(args.api!.get).toHaveBeenCalledWith(PLACEMENTS_PROJECT_ID, "pain_point", DRAFT_ARTEFACT_ID);
    await expect(takePendingPlacements(PLACEMENTS_PROJECT_ID, "pain_point")).toEqual([
      { component_id: "c-hw", category_id: "k-cool" },
      { component_id: "c-sw", category_id: null },
    ]);
  },
};

export const HiddenWhenTheCallerCannotPlaceThisType: Story = {
  args: { api: buildPlacementsApi(buildRecordPlacements({ can_edit: false, placements: [] })) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.get).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("button", { name: "Components and categories" })).not.toBeInTheDocument();
  },
};

export const HiddenForARecordThatKeepsItsOwnComponent: Story = {
  args: { api: buildPlacementsApi(buildRecordPlacements({ can_edit: false, managed_on_record: true })), artefactType: "requirement" },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.get).toHaveBeenCalled());
    await expect(within(canvasElement).queryByText("Components")).not.toBeInTheDocument();
  },
};

export const HiddenWhenTheProjectHasNoComponents: Story = {
  args: { api: buildPlacementsApi(undefined, { tree: fn(async () => ({ components: [], categories: [] })) }) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.tree).toHaveBeenCalled());
    await expect(within(canvasElement).queryByText("Components")).not.toBeInTheDocument();
  },
};

export const HiddenWhenTheReadFails: Story = {
  args: { api: buildPlacementsApi(undefined, { get: fn(async () => { throw new Error("nope"); }) }) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.get).toHaveBeenCalled());
    await expect(within(canvasElement).queryByText("Components")).not.toBeInTheDocument();
  },
};
