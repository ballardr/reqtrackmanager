import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { DRAFT_ARTEFACT_ID } from "../api/artefactLinks";
import { buildRecordTags, buildRecordTagsApi, openTagPicker, TAGS_PROJECT_ID } from "../testing/tagsFixtures";
import { TagField } from "./TagField";

function Harness(props: Omit<React.ComponentProps<typeof TagField>, "value" | "onChange">) {
  const [value, setValue] = useState<string[]>([]);
  return (
    <div>
      <TagField {...props} value={value} onChange={setValue} />
      <output aria-label="Chosen">{value.join("|")}</output>
    </div>
  );
}

/**
 * The "Tags" field of a create form. It asks about a record that does not exist yet, so it shows the
 * vocabulary and mode that will apply, and nothing when the caller cannot tag this kind of record.
 */
const meta: Meta<typeof Harness> = {
  title: "Components/TagField",
  component: Harness,
  args: { projectId: TAGS_PROJECT_ID, artefactType: "pain_point" },
};
export default meta;

type Story = StoryObj<typeof Harness>;

export const ChoosingTagsForANewRecord: Story = {
  args: { api: buildRecordTagsApi(buildRecordTags({ tags: [] })) },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await openTagPicker(canvas), "sec");
    await userEvent.click(await within(document.body).findByRole("option", { name: "Security" }));
    await expect(canvas.getByLabelText("Chosen").textContent).toBe("Security");
    await expect(args.api!.get).toHaveBeenCalledWith(TAGS_PROJECT_ID, "pain_point", DRAFT_ARTEFACT_ID);
    await expect(canvas.getByText(/Tags are added when the record is saved/)).toBeInTheDocument();
  },
};

export const HiddenWhenTheCallerCannotTagThisType: Story = {
  args: { api: buildRecordTagsApi(buildRecordTags({ can_edit: false, tags: [] })) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.get).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("button", { name: "Add tag" })).not.toBeInTheDocument();
  },
};

export const HiddenWhenTheReadFails: Story = {
  args: { api: buildRecordTagsApi(undefined, { get: fn(async () => { throw new Error("nope"); }) }) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.get).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("button", { name: "Add tag" })).not.toBeInTheDocument();
  },
};
