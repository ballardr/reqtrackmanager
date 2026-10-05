import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { buildFileAsset, buildUser, withAuth, withToast } from "../../testing/storybook-helpers";
import { RecordDiscussion, type DiscussionApi } from "./RecordDiscussion";
import type { PersonaComment } from "./types";

const COMMENT: PersonaComment = {
  id: "c1", persona_id: "p1", author_id: "user-1", author_display_name: "Alex Morgan", body: "First thoughts",
  created_at: "2026-01-10T09:00:00Z", edited_at: null, attachments: [],
};

function makeApi(overrides: Partial<DiscussionApi<PersonaComment>> = {}): DiscussionApi<PersonaComment> {
  return {
    listComments: fn(async () => [COMMENT]),
    addComment: fn(async (_id: string, _rid: string, body: string) => ({ ...COMMENT, id: "c2", body })),
    editComment: fn(async (_id: string, _rid: string, _cid: string, body: string) => ({ ...COMMENT, body })),
    uploadCommentAttachment: fn(async () => buildFileAsset({ id: "f9", filename: "note.txt" })),
    removeCommentAttachment: fn(async () => undefined),
    listFiles: fn(async () => [buildFileAsset({ id: "f1", filename: "brief.pdf" })]),
    uploadFile: fn(async () => buildFileAsset({ id: "f2", filename: "new.txt" })),
    unlinkFile: fn(async () => undefined),
    ...overrides,
  };
}

const meta: Meta<typeof RecordDiscussion> = {
  title: "Modules/Stakeholders/RecordDiscussion",
  component: RecordDiscussion,
  decorators: [withAuth(buildUser({ id: "user-1" })), withToast()],
  args: { scopeId: "project-1", recordId: "p1", noun: "Persona", currentUserId: "user-1", attachmentsReadOnly: false },
};
export default meta;

type Story = StoryObj<typeof RecordDiscussion>;

export const LoadsAttachmentsAndComments: Story = {
  args: { api: makeApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("First thoughts")).toBeInTheDocument());
    await expect(canvas.getByRole("heading", { name: "Attachments" })).toBeInTheDocument();
    await expect(canvas.getByText("brief.pdf")).toBeInTheDocument();
    await expect(args.api.listComments).toHaveBeenCalledWith("project-1", "p1");
  },
};

export const PostingACommentAddsItToTheThread: Story = {
  args: { api: makeApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByText("First thoughts"));
    await userEvent.type(canvas.getByRole("textbox"), "A second comment");
    await userEvent.click(canvas.getByRole("button", { name: /^(Post|Comment|Add comment)/ }));
    await waitFor(() => expect(args.api.addComment).toHaveBeenCalledWith("project-1", "p1", "A second comment"));
    await waitFor(() => expect(canvas.getByText("A second comment")).toBeInTheDocument());
  },
};

export const ReadOnlyAttachmentsExplainWhy: Story = {
  args: { api: makeApi({ listFiles: fn(async () => []) }), attachmentsReadOnly: true, attachmentsHint: "Managed from the organisation view." },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("Managed from the organisation view.")).toBeInTheDocument());
  },
};

export const LoadFailureIsAToastNotACrash: Story = {
  args: { api: makeApi({ listComments: fn(async () => { throw new Error("boom"); }) }) },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(document.body).getByText("boom")).toBeInTheDocument());
    await expect(within(canvasElement).getByRole("heading", { name: "Attachments" })).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...LoadsAttachmentsAndComments, globals: { theme: "dark" } };
