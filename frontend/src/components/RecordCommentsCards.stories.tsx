import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter } from "react-router-dom";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildComment, buildPin, fakeRecordComments } from "../testing/recordCommentsFake";
import { RecordCommentsCards } from "./RecordCommentsCards";

/** The generic comment cards of a record page: the record's own comments and, read-only, the threads pinned to it on drawings. */
const meta: Meta<typeof RecordCommentsCards> = {
  title: "Components/RecordCommentsCards",
  component: RecordCommentsCards,
  decorators: [(Story) => <MemoryRouter><Story /></MemoryRouter>],
};
export default meta;

type Story = StoryObj<typeof RecordCommentsCards>;

export const ListsOrdinaryCommentsAndPostsANewOne: Story = {
  args: {
    projectId: "project-1", artefactType: "architecture_element", recordId: "el-1", currentUserId: "user-1",
    client: fakeRecordComments({ can_pin: false, comments: [buildComment({ id: "c-1", body: "First thought." })] }),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("First thought.")).toBeInTheDocument();
    await userEvent.type(canvas.getByRole("textbox", { name: "Add a comment" }), "A second thought");
    await userEvent.click(canvas.getByRole("button", { name: "Add comment" }));
    await waitFor(() => expect(canvas.getByText("A second thought")).toBeInTheDocument());
    expect((args.client as ReturnType<typeof fakeRecordComments>).state().comments).toHaveLength(2);
  },
};

export const PinnedThreadsOfOtherRecordsAreNotListedAsOwnComments: Story = {
  args: {
    projectId: "project-1", artefactType: "architecture_diagram", recordId: "dgm-1", currentUserId: "user-1",
    client: fakeRecordComments({
      pins: [buildPin({ id: "p-1" })],
      comments: [buildComment({ id: "c-1", pin_id: "p-1", body: "Pinned elsewhere." }), buildComment({ id: "c-2", body: "Ordinary." })],
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Ordinary.")).toBeInTheDocument();
    await expect(canvas.queryByText("Pinned elsewhere.")).toBeNull();
  },
};
