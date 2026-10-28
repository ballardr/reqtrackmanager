/**
 * Module: components/reportLayoutRichTextExtensions
 *
 * The rich-text editor's schema: the TipTap node definitions for the editor nodes the converter
 * (`utils/reportLayoutDoc`) produces, with their attributes held as plain data and each drawn by its node view.
 *
 * Responsibilities: name the nodes and their content rules (a document is blocks; a text block is paragraphs, bullet
 * lists and headings; a container holds slots; a slot holds blocks), keep Enter in a heading from splitting it, and
 * list every extension the editor loads.
 *
 * Design decisions: the only marks are the four the report engine draws (bold, italic, code, link), only in a text
 * block, and there are no image or raw HTML nodes, so nothing the engine would not interpret can be typed or pasted
 * into a layout; pasted rich text is reduced to what the schema allows. A link is made only through the link dialog:
 * typing or pasting an address does not link it, a click does not follow it, and an address `linkProblem` refuses
 * (the server's rule) is never accepted as a link, even from pasted HTML.
 */
import { Node } from "@tiptap/core";
import Bold from "@tiptap/extension-bold";
import Code from "@tiptap/extension-code";
import Document from "@tiptap/extension-document";
import Italic from "@tiptap/extension-italic";
import Link from "@tiptap/extension-link";
import { BulletList, ListItem, OrderedList } from "@tiptap/extension-list";
import Paragraph from "@tiptap/extension-paragraph";
import Text from "@tiptap/extension-text";
import { Gapcursor, UndoRedo } from "@tiptap/extensions";
import { ReactNodeViewRenderer } from "@tiptap/react";

import { DOC } from "../utils/reportLayoutDoc";
import { linkProblem } from "../utils/reportLayoutProse";
import { ContainerView, HeadingView, LeafView, RawTextView, SlotView, TextView } from "./ReportLayoutRichTextViews";

// ---- the nodes ----------------------------------------------------------------------------------------------------

/** An attribute holding plain data, kept out of the HTML. */
const data = (fallback: unknown) => ({ default: fallback, rendered: false });

const LayoutHeading = Node.create({
  name: DOC.heading,
  group: "layoutNode",
  content: "text*",
  marks: "",
  defining: true,
  addAttributes: () => ({ props: data({}) }),
  parseHTML: () => [{ tag: "h2[data-layout-heading]" }],
  renderHTML: () => ["h2", { "data-layout-heading": "" }, 0],
  addNodeView: () => ReactNodeViewRenderer(HeadingView),
  addKeyboardShortcuts() {
    // Enter ends the heading: the next thing typed is a text block after it.
    return {
      Enter: ({ editor }) => {
        if (editor.state.selection.$from.parent.type.name !== DOC.heading) return false;
        const { $from } = editor.state.selection;
        return editor.chain().insertContentAt($from.after(), { type: DOC.text, attrs: { props: {} }, content: [{ type: DOC.paragraph }] }).focus().run();
      },
    };
  },
});

const LayoutText = Node.create({
  name: DOC.text,
  group: "layoutNode",
  content: "(paragraph | bulletList | orderedList | layoutMdHeading)+",
  defining: true,
  addAttributes: () => ({ props: data({}) }),
  parseHTML: () => [{ tag: "div[data-layout-text]" }],
  renderHTML: () => ["div", { "data-layout-text": "" }, 0],
  addNodeView: () => ReactNodeViewRenderer(TextView),
});

const LayoutMdHeading = Node.create({
  name: DOC.mdHeading,
  content: "text*",
  marks: "",
  defining: true,
  addAttributes: () => ({ level: data(1) }),
  parseHTML: () => [{ tag: "h3[data-md-heading]" }],
  renderHTML: ({ node }) => ["h3", { "data-md-heading": "", "data-level": String(node.attrs.level) }, 0],
});

const LayoutRawText = Node.create({
  name: DOC.raw,
  group: "layoutNode",
  atom: true,
  addAttributes: () => ({ props: data({}), markdown: data("") }),
  parseHTML: () => [{ tag: "div[data-layout-raw]" }],
  renderHTML: () => ["div", { "data-layout-raw": "" }],
  addNodeView: () => ReactNodeViewRenderer(RawTextView),
});

const LayoutLeaf = Node.create({
  name: DOC.leaf,
  group: "layoutNode",
  atom: true,
  addAttributes: () => ({ node: data({}) }),
  parseHTML: () => [{ tag: "div[data-layout-leaf]" }],
  renderHTML: () => ["div", { "data-layout-leaf": "" }],
  addNodeView: () => ReactNodeViewRenderer(LeafView),
});

const LayoutBlock = Node.create({
  name: DOC.block,
  group: "layoutNode",
  content: "layoutSlot*",
  isolating: true,
  addAttributes: () => ({ type: data(""), props: data({}) }),
  parseHTML: () => [{ tag: "div[data-layout-block]" }],
  renderHTML: () => ["div", { "data-layout-block": "" }, 0],
  addNodeView: () => ReactNodeViewRenderer(ContainerView),
});

const LayoutSlot = Node.create({
  name: DOC.slot,
  content: "layoutNode*",
  isolating: true,
  addAttributes: () => ({ key: data("children") }),
  parseHTML: () => [{ tag: "div[data-layout-slot]" }],
  renderHTML: () => ["div", { "data-layout-slot": "" }, 0],
  addNodeView: () => ReactNodeViewRenderer(SlotView),
});

/** The layout document: any number of blocks. */
const LayoutDocument = Document.extend({ content: "layoutNode*" });
/** A link carries an address the server would accept and is never followed from inside the editor. */
const LayoutLink = Link.configure({
  openOnClick: false,
  autolink: false,
  linkOnPaste: false,
  isAllowedUri: (url: string) => linkProblem(url) === null,
  HTMLAttributes: { rel: "noopener noreferrer", target: null },
});

/** A list item holds one paragraph (an item is one line of text). */
const LayoutListItem = ListItem.extend({ content: "paragraph" });

/** Every extension of the layout editor. */
export const layoutExtensions = [
  LayoutDocument, Text, Paragraph, BulletList, OrderedList, LayoutListItem, Bold, Italic, Code, LayoutLink,
  LayoutHeading, LayoutText, LayoutMdHeading, LayoutRawText, LayoutLeaf, LayoutBlock, LayoutSlot, Gapcursor, UndoRedo,
];
