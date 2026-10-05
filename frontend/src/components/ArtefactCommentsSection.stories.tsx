import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { type ArtefactComment, ArtefactCommentsSection } from "./ArtefactCommentsSection";

/** A generic comment fixture; any module comment type with these fields renders identically. */
function comment(overrides: Partial<ArtefactComment> = {}): ArtefactComment {
  return {
    id: "comment-1", author_id: "user-1", author_display_name: "Alex Morgan",
    body: "Worth double-checking the target date against the roadmap before we approve.",
    created_at: "2026-02-02T10:00:00Z", edited_at: null, attachments: [],
    ...overrides,
  };
}

const meta: Meta<typeof ArtefactCommentsSection> = {
  title: "Components/ArtefactCommentsSection",
  component: ArtefactCommentsSection,
  args: { onPost: fn(async (body: string) => comment({ id: "comment-new", body })) },
};
export default meta;

type Story = StoryObj<typeof ArtefactCommentsSection>;

export const EmptyThread: Story = {
  args: { comments: [] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("No comments yet.")).toBeInTheDocument();
  },
};

export const WithComments: Story = {
  args: {
    comments: [
      comment(),
      comment({ id: "comment-2", author_display_name: "Jordan Lee", body: "Agreed, flagging to the steering group.", edited_at: "2026-02-02T11:00:00Z" }),
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Alex Morgan")).toBeInTheDocument();
    await expect(canvas.getByText("Jordan Lee")).toBeInTheDocument();
    await expect(canvas.getByText(/\(edited\)/)).toBeInTheDocument();
  },
};

export const PostComment: Story = {
  args: { comments: [] },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText("Add a comment"), "Looks good to me.");
    await userEvent.click(canvas.getByRole("button", { name: "Add comment" }));
    await waitFor(() => expect(args.onPost).toHaveBeenCalledWith("Looks good to me."));
  },
};

export const AuthorCanEdit: Story = {
  args: { comments: [comment()], currentUserId: "user-1", onEdit: fn() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Edit comment" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...WithComments };
export const DarkTheme: Story = { ...WithComments, globals: { theme: "dark" } };
