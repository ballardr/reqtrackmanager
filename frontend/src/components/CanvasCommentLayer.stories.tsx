import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildComment, buildPin, fakeRecordComments } from "../testing/recordCommentsFake";
import { CanvasCommentLayer } from "./CanvasCommentLayer.fixture";

/**
 * Comments on the shared graph canvas for a record that is not an architecture diagram: the layer needs only the record and
 * how its anchors map to canvas ids, so another module's canvas gets the same comment mode, markers and pop-over.
 */
const meta: Meta<typeof CanvasCommentLayer> = {
  title: "Components/CanvasCommentLayer",
  component: CanvasCommentLayer,
  parameters: { layout: "padded" },
  loaders: [async () => { await import("./GraphCanvasView"); return {}; }],
};
export default meta;

type Story = StoryObj<typeof CanvasCommentLayer>;

const SECOND = buildComment({ id: "c-2", pin_id: "p-1", author_id: "user-2", author_display_name: "Sam Owner", body: "Agreed, adding it.", can_edit: false, can_delete: false });

/** A thread's marker shows the first author's initials and a count; clicking it opens the thread with its replies. */
export const MarkersOpenTheirThread: Story = {
  args: {
    client: fakeRecordComments({
      pins: [buildPin({ id: "p-1", anchor_kind: "node", anchor_key: "gateway", comment_count: 2 })],
      comments: [buildComment({ id: "c-1", pin_id: "p-1", body: "Missing the retry path." }), SECOND],
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const marker = await canvas.findByRole("button", { name: /Comment thread by Alex Reviewer, 2 comments/ });
    expect(marker).toHaveTextContent("AR");
    await userEvent.click(marker);
    const thread = within(await within(document.body).findByRole("dialog", { name: "Comment thread" }));
    expect(thread.getByText("Missing the retry path.")).toBeInTheDocument();
    expect(thread.getByText("Agreed, adding it.")).toBeInTheDocument();
    // Another person's comment offers neither Edit nor Delete.
    expect(thread.getAllByRole("button", { name: "Edit" })).toHaveLength(1);
  },
};

/** In comment mode a click on the canvas opens a composer; posting leaves a marker and the layout stays unchanged. */
export const CommentModePlacesAComment: Story = {
  args: { client: fakeRecordComments() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Comment" }));
    await userEvent.click(canvasElement.querySelector(".react-flow__pane") as HTMLElement);
    const composer = within(await within(document.body).findByRole("dialog", { name: "New comment" }));
    await userEvent.type(composer.getByRole("textbox", { name: "New comment" }), "A gap in the design");
    await userEvent.click(composer.getByRole("button", { name: "Comment" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: /Comment thread by Alex Reviewer, 1 comment/ })).toBeInTheDocument());
    const stored = (args.client as ReturnType<typeof fakeRecordComments>).state();
    expect(stored.pins[0]).toMatchObject({ anchor_kind: "none" });
    expect(stored.comments[0].body).toBe("A gap in the design");
  },
};

/** A click on a box anchors the comment to it, by the module's key for that box. */
export const AClickOnABoxAnchorsTheComment: Story = {
  args: { client: fakeRecordComments() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Comment" }));
    await userEvent.click(await canvas.findByLabelText("Gateway, node"));
    const composer = within(await within(document.body).findByRole("dialog", { name: "New comment" }));
    await userEvent.type(composer.getByRole("textbox", { name: "New comment" }), "Rename this");
    await userEvent.click(composer.getByRole("button", { name: "Comment" }));
    await waitFor(() => expect((args.client as ReturnType<typeof fakeRecordComments>).state().pins).toHaveLength(1));
    expect((args.client as ReturnType<typeof fakeRecordComments>).state().pins[0]).toMatchObject({ anchor_kind: "node", anchor_key: "key:gateway" });
  },
};

/** Reply, resolve and reopen: the marker is outlined and labelled resolved, and Show resolved hides it. */
export const ReplyResolveAndHide: Story = {
  args: {
    client: fakeRecordComments({ pins: [buildPin({ id: "p-1" })], comments: [buildComment({ id: "c-1", pin_id: "p-1" })] }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: /Comment thread by Alex Reviewer, 1 comment/ }));
    const thread = within(await within(document.body).findByRole("dialog", { name: "Comment thread" }));
    await userEvent.type(thread.getByRole("textbox", { name: "Reply" }), "Done");
    await userEvent.click(thread.getByRole("button", { name: "Reply" }));
    await waitFor(() => expect(thread.getByText("Done")).toBeInTheDocument());
    await userEvent.click(thread.getByRole("button", { name: "Resolve" }));
    await waitFor(() => expect(thread.getByRole("button", { name: "Reopen" })).toBeInTheDocument());
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(canvas.getByRole("button", { name: /Resolved comment thread/ })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("checkbox", { name: "Show resolved" }));
    await waitFor(() => expect(canvas.queryByRole("button", { name: /Resolved comment thread/ })).toBeNull());
  },
};

/** A thread whose box is not on the canvas stays at its last place and says so. */
export const ADetachedThreadSaysItsBoxIsGone: Story = {
  args: {
    client: fakeRecordComments({
      pins: [buildPin({ id: "p-1", anchor_kind: "node", anchor_key: "removed-box" })],
      comments: [buildComment({ id: "c-1", pin_id: "p-1" })],
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: /Comment thread/ }));
    expect(await within(document.body).findAllByText(/no longer on the drawing/)).not.toHaveLength(0);
  },
};

/** Comments can be hidden altogether; the thread's own data is untouched. */
export const ShowCommentsHidesEveryMarker: Story = {
  args: {
    client: fakeRecordComments({ pins: [buildPin({ id: "p-1" })], comments: [buildComment({ id: "c-1", pin_id: "p-1" })] }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("button", { name: /Comment thread/ });
    await userEvent.click(canvas.getByRole("checkbox", { name: "Show comments" }));
    await waitFor(() => expect(canvas.queryByRole("button", { name: /Comment thread/ })).toBeNull());
  },
};
