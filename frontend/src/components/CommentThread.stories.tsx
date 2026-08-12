import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";

import type { Comment } from "../api/types";
import { buildComment } from "../testing/storybook-helpers";
import { CommentThread } from "./CommentThread";

const AUTHOR_ID = "user-1";
const OTHER_USER_ID = "user-2";

const baseComments: Comment[] = [
  buildComment({ id: "c1", author_id: AUTHOR_ID, author_display_name: "Alex Morgan", body: "Looks good to me." }),
  buildComment({
    id: "c2",
    author_id: OTHER_USER_ID,
    author_display_name: "Jamie Lee",
    body: "Can we clarify the expiry window?",
    reaction_count: 2,
    reacted_by_me: true,
  }),
];

/** All I/O is via callback props, so despite its size CommentThread is
 * fully mockable with props alone (see the QA inventory) — this wrapper
 * keeps posted/edited comments in local state so a story reads like the
 * real controlled usage in RequirementDetailPage/ChangeRequestDetailPage. */
function Interactive({ currentUserId = AUTHOR_ID }: { currentUserId?: string }) {
  const [comments, setComments] = useState<Comment[]>(baseComments);
  return (
    <CommentThread
      comments={comments}
      currentUserId={currentUserId}
      onPost={async (body) => {
        const comment = buildComment({ id: `posted-${comments.length}`, author_id: currentUserId, body });
        setComments((c) => [...c, comment]);
        return comment;
      }}
      onToggleReaction={async (commentId, reacted) => {
        setComments((c) =>
          c.map((x) =>
            x.id === commentId
              ? { ...x, reacted_by_me: !reacted, reaction_count: x.reaction_count + (reacted ? -1 : 1) }
              : x
          )
        );
      }}
      onEdit={async (commentId, body) => {
        setComments((c) => c.map((x) => (x.id === commentId ? { ...x, body, edited_at: new Date().toISOString() } : x)));
      }}
      onUploadAttachment={async () => {}}
      onRemoveAttachment={async () => {}}
    />
  );
}

const meta: Meta<typeof Interactive> = {
  title: "Components/CommentThread",
  component: Interactive,
};
export default meta;

type Story = StoryObj<typeof Interactive>;

export const ThreadWithReactions: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Looks good to me.")).toBeInTheDocument();
    await expect(canvas.getByText("2")).toBeInTheDocument();
  },
};

export const PostNewComment: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByPlaceholderText("Add comment");
    await userEvent.type(input, "New comment body");
    await userEvent.click(canvas.getByRole("button", { name: "Add comment" }));
    await expect(canvas.getByText("New comment body")).toBeInTheDocument();
  },
};

export const ToggleReaction: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Jamie Lee's comment already has `reacted_by_me: true` (count 2);
    // toggling it off should drop the count to 1.
    const [reactedButton] = canvas.getAllByRole("button", { name: "Like this comment", pressed: true });
    await userEvent.click(reactedButton);
    await expect(canvas.getByText("1")).toBeInTheDocument();
  },
};

/** Only the comment's own author sees the Edit control — currentUserId
 * matches Jamie Lee's comment here, not Alex Morgan's, so only one Edit
 * icon should render. */
export const EditOnlyVisibleToAuthor: Story = {
  args: { currentUserId: OTHER_USER_ID },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const editButtons = canvas.getAllByTitle("Edit");
    await expect(editButtons).toHaveLength(1);
  },
};

export const NoUploadOrEditCallbacks: Story = {
  render: () => (
    <CommentThread comments={baseComments} onPost={async (body) => buildComment({ body })} onToggleReaction={fn()} />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByTitle("Attach a file")).not.toBeInTheDocument();
    await expect(canvas.queryByTitle("Edit")).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ThreadWithReactions, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ThreadWithReactions, globals: { theme: "dark" } };
