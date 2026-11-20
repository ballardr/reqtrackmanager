import type { Meta, StoryObj } from "@storybook/react-vite";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { expect, within } from "storybook/test";

import { type RichTextFeatures, RichTextToolbar } from "./RichTextToolbar";

/** The formatting toolbar shared by the policy editor and the visual Markdown editor. */
const meta: Meta = { title: "Components/RichTextToolbar" };
export default meta;

type Story = StoryObj;

/** A bare editor with only the base extensions, so the optional buttons are the ones the toolbar is asked for. */
function Harness({ features }: { features?: RichTextFeatures }) {
  const editor = useEditor({ extensions: [StarterKit], content: "<p>Text</p>" });
  if (!editor) return null;
  return (
    <>
      <RichTextToolbar editor={editor} features={features} />
      <EditorContent editor={editor} />
    </>
  );
}

export const ShowsTheCommonButtonsOnly: Story = {
  render: () => <Harness />,
  play: async ({ canvasElement }) => {
    const toolbar = within(await within(canvasElement).findByRole("toolbar", { name: "Text formatting" }));
    for (const name of ["Bold", "Italic", "Heading 1", "Heading 2", "Heading 3", "Bulleted list", "Numbered list", "Quotation", "Horizontal rule", "Link", "Undo", "Redo"]) {
      await expect(toolbar.getByRole("button", { name })).toBeInTheDocument();
    }
    for (const name of ["Inline code", "Code block", "Table", "Diagram"]) {
      await expect(toolbar.queryByRole("button", { name })).toBeNull();
    }
    // Nothing to undo yet.
    await expect(toolbar.getByRole("button", { name: "Undo" })).toBeDisabled();
  },
};

export const OffersTheOptionalButtonsAFieldAsksFor: Story = {
  render: () => <Harness features={{ code: true, codeBlock: true, diagram: true }} />,
  play: async ({ canvasElement }) => {
    const toolbar = within(await within(canvasElement).findByRole("toolbar", { name: "Text formatting" }));
    for (const name of ["Inline code", "Code block", "Diagram"]) {
      await expect(toolbar.getByRole("button", { name })).toBeInTheDocument();
    }
    await expect(toolbar.queryByRole("button", { name: "Table" })).toBeNull();
  },
};
