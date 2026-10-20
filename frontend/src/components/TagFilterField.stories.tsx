import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { useTagFilter } from "../hooks/useTagFilter";
import { buildRecordTagsApi, buildVocabulary, TAGS_PROJECT_ID } from "../testing/tagsFixtures";
import { TagFilterField } from "./TagFilterField";

function Harness({ api }: { api: React.ComponentProps<typeof TagFilterField>["api"] }) {
  const filter = useTagFilter();
  return (
    <div className="stack" style={{ maxWidth: 260 }}>
      <TagFilterField projectId={TAGS_PROJECT_ID} filter={filter} api={api} />
      <output aria-label="Query">{filter.query}</output>
    </div>
  );
}

/**
 * The tag filter of a list's filter panel: tick tags, and once two or more are ticked choose whether
 * a record needs any or all of them. The list page sends `query` with its list read.
 */
const meta: Meta<typeof Harness> = {
  title: "Components/TagFilterField",
  component: Harness,
};
export default meta;

type Story = StoryObj<typeof Harness>;

export const TickingTagsBuildsTheQuery: Story = {
  args: { api: buildRecordTagsApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Tags" }));
    await userEvent.click(await within(document.body).findByRole("checkbox", { name: "Safety" }));
    await expect(canvas.getByLabelText("Query").textContent).toBe("tag=Safety&tag_mode=any");
    await userEvent.click(await within(document.body).findByRole("checkbox", { name: "Release 2" }));
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Match" }), "all");
    await expect(canvas.getByLabelText("Query").textContent).toBe("tag=Safety&tag=Release+2&tag_mode=all");
  },
};

/** A project with no tags shows no filter at all. */
export const HiddenWhenTheProjectHasNoTags: Story = {
  args: { api: buildRecordTagsApi(undefined, { vocabulary: fn(async () => buildVocabulary({ tags: [] })) }) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.vocabulary).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("button", { name: "Tags" })).not.toBeInTheDocument();
  },
};
