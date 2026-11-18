import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { buildPlace, buildPlacementsApi, buildRecordPlacements } from "../testing/placementsFixtures";
import { buildChip, buildRecordTags, buildRecordTagsApi, openTagPicker, TAGS_PROJECT_ID } from "../testing/tagsFixtures";
import { withToast } from "../testing/storybook-helpers";
import { RecordTags } from "./RecordTags";

/**
 * The tags of one record in its header. Someone who may tag it edits them in place and each change
 * is saved at once; everyone else sees the chips (or nothing, when there are none).
 */
const meta: Meta<typeof RecordTags> = {
  title: "Components/RecordTags",
  component: RecordTags,
  decorators: [withToast()],
  args: { projectId: TAGS_PROJECT_ID, artefactType: "requirement", artefactId: "req-1" },
};
export default meta;

type Story = StoryObj<typeof RecordTags>;

export const AddingATagSavesTheWholeSet: Story = {
  args: { api: buildRecordTagsApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await openTagPicker(canvas), "sec");
    await userEvent.click(await within(document.body).findByRole("option", { name: "Security" }));
    await waitFor(() => expect(args.api!.set).toHaveBeenCalledWith(TAGS_PROJECT_ID, "requirement", "req-1", ["Safety", "Security"]));
    await expect(await canvas.findByRole("button", { name: "Remove tag Security" })).toBeInTheDocument();
  },
};

export const RemovingATagSavesWithoutIt: Story = {
  args: { api: buildRecordTagsApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Remove tag Safety" }));
    await waitFor(() => expect(args.api!.set).toHaveBeenCalledWith(TAGS_PROJECT_ID, "requirement", "req-1", []));
  },
};

/** A refused save puts the tags back as they were and says why. */
export const ARefusedSaveIsRevertedWithAMessage: Story = {
  args: {
    api: buildRecordTagsApi(buildRecordTags({ restricted: false }), {
      set: fn(async () => { throw new Error("'Security' is not in the tag list."); }),
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await openTagPicker(canvas), "sec");
    await userEvent.click(await within(document.body).findByRole("option", { name: "Security" }));
    await waitFor(() => expect(canvas.queryByRole("button", { name: "Remove tag Security" })).not.toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Remove tag Safety" })).toBeInTheDocument();
    await expect(await within(document.body).findByText(/Could not save the tags: 'Security' is not in the tag list\./)).toBeInTheDocument();
  },
};

/** Without permission to tag, the chips are shown without a box or remove controls. */
export const ReadOnlyForSomeoneWhoCannotTag: Story = {
  args: { api: buildRecordTagsApi(buildRecordTags({ can_edit: false })) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Safety")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Add tag" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button")).not.toBeInTheDocument();
  },
};

/** No tags and no right to add any: nothing at all, so the header stays clean. */
export const NothingWhenThereAreNoTagsAndNoRightToAddAny: Story = {
  args: { api: buildRecordTagsApi(buildRecordTags({ can_edit: false, tags: [] })) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.get).toHaveBeenCalled());
    await expect(canvasElement.textContent).toBe("");
  },
};

/** A tag that cannot be read leaves the header without tags rather than with an error. */
export const AFailedReadShowsNothing: Story = {
  args: { api: buildRecordTagsApi(undefined, { get: fn(async () => { throw new Error("nope"); }) }) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.get).toHaveBeenCalled());
    await expect(canvasElement.textContent).toBe("");
  },
};

/** In a restricted project the box is a picker only. */
export const RestrictedProjectOffersTheListOnly: Story = {
  args: { api: buildRecordTagsApi(buildRecordTags({ restricted: true, tags: [] })) },
  play: async ({ canvasElement }) => {
    const input = await openTagPicker(within(canvasElement));
    await expect(input).toHaveAttribute("placeholder", "Choose a tag…");
  },
};

export const ChangedCallbackFiresAfterASave: Story = {
  args: { api: buildRecordTagsApi(buildRecordTags({ tags: [buildChip("Safety")] })), onChanged: fn() },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Remove tag Safety" }));
    await waitFor(() => expect(args.onChanged).toHaveBeenCalled());
  },
};

/** A fake whose `get` returns what `set` last saved, as the server does. */
function statefulTagsApi() {
  let current = buildRecordTags();
  const base = buildRecordTagsApi();
  return buildRecordTagsApi(current, {
    get: fn(async () => current),
    set: fn(async (p: string, t: string, i: string, names: string[]) => {
      current = await base.set(p, t, i, names);
      return current;
    }),
  });
}

/** The compact form: read-only chips for the tags and the components on the badge line, and one edit button. */
export const InlineShowsChipsAndOneEditButton: Story = {
  args: { inline: true, api: buildRecordTagsApi(), placementsApi: buildPlacementsApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Safety")).toBeInTheDocument();
    await expect(await canvas.findByText("Hardware / Cooling")).toBeInTheDocument();
    // The chips carry no remove control and no picker is on the line: editing is behind the one button.
    await expect(canvas.queryByRole("button", { name: "Remove tag Safety" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Tags and components" })).toBeInTheDocument();
  },
};

/** Changes are made in the dialog, saved at once, and the chips on the line follow. */
export const InlineEditsInADialogAndTheChipsFollow: Story = {
  args: { inline: true, api: statefulTagsApi(), placementsApi: buildPlacementsApi(), onChanged: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Tags and components" }));
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Tags and components" }));
    await userEvent.click(await dialog.findByRole("button", { name: "Remove tag Safety" }));
    await waitFor(() => expect(args.api!.set).toHaveBeenCalledWith(TAGS_PROJECT_ID, "requirement", "req-1", []));
    await expect(args.onChanged).toHaveBeenCalled();
    await waitFor(() => expect(canvas.queryByText("Safety")).not.toBeInTheDocument());
  },
};

/** A record with no tags or components shows no line and no empty text; someone who may edit still has the button. */
export const InlineWithNothingSetShowsOnlyTheButton: Story = {
  args: {
    inline: true,
    api: buildRecordTagsApi(buildRecordTags({ tags: [] })),
    placementsApi: buildPlacementsApi(buildRecordPlacements({ placements: [] })),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("button", { name: "Tags and components" })).toBeInTheDocument();
    await expect(canvas.queryByText("Not placed in a component")).not.toBeInTheDocument();
    await expect(canvas.queryByText("No tags")).not.toBeInTheDocument();
  },
};

/** With nothing set and no right to change it, nothing is drawn at all. */
export const InlineDrawsNothingWithNothingSetAndNoRightToChange: Story = {
  args: {
    inline: true,
    api: buildRecordTagsApi(buildRecordTags({ tags: [], can_edit: false })),
    placementsApi: buildPlacementsApi(buildRecordPlacements({ placements: [], can_edit: false })),
  },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.get).toHaveBeenCalled());
    await waitFor(() => expect(args.placementsApi!.get).toHaveBeenCalled());
    await expect(canvasElement.textContent).toBe("");
  },
};

/** Read-only chips for someone who cannot change them, with no button. */
export const InlineReadOnlyHasNoButton: Story = {
  args: {
    inline: true,
    api: buildRecordTagsApi(buildRecordTags({ can_edit: false })),
    placementsApi: buildPlacementsApi(buildRecordPlacements({ can_edit: false, placements: [buildPlace("c-sw")] })),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Safety")).toBeInTheDocument();
    await expect(await canvas.findByText("Software")).toBeInTheDocument();
    await expect(canvas.queryByRole("button")).not.toBeInTheDocument();
  },
};
