import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { buildChip, buildRecordTags, buildRecordTagsApi, TAGS_PROJECT_ID } from "../testing/tagsFixtures";
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
    await userEvent.type(await canvas.findByRole("combobox", { name: "Tags" }), "sec");
    await userEvent.click(await canvas.findByRole("option", { name: "Security" }));
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
    await userEvent.type(await canvas.findByRole("combobox", { name: "Tags" }), "sec");
    await userEvent.click(await canvas.findByRole("option", { name: "Security" }));
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
    await expect(canvas.queryByRole("combobox")).not.toBeInTheDocument();
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
    const input = await within(canvasElement).findByRole("combobox", { name: "Tags" });
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
