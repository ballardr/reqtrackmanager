/**
 * Module: utils/visualImageNode
 *
 * The picture node of the Visual Markdown editor: one inline, indivisible node that holds an attachment's file id, its
 * alternative text and its caption, read from and written back as `![alt](attachment:<file id> "caption")`.
 *
 * Responsibilities: read a picture of the record's own attachment into a node and write it back exactly as
 *   `pictureMarkdown` does, so a text with pictures survives the editor unchanged; carry the node through copy and
 *   paste inside the editor (`data-picture` markup, with no address).
 *
 * Design decisions:
 * - The node is an atom, like the equation node: the editor never reads or escapes what is inside it.
 * - Only an attachment picture is a node. An image with an outside address stays ordinary text, which makes the field
 *   fall back to Write: a picture is never an address the page would request.
 * - The editor extends the node with a view (`VisualMarkdownEditor`); a headless editor (the round-trip check) uses it
 *   as it is, so nothing here draws or requests anything.
 *
 * Dependencies: TipTap (MIT), `utils/markdownPicture`.
 */
import { mergeAttributes, Node, type Editor } from "@tiptap/core";

import { pictureMarkdown, PICTURE_START, unescapeLine } from "./markdownPicture";

/** The picture node. */
export const PictureNode = Node.create({
  name: "picture",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,
  draggable: false,

  addAttributes() {
    return { fileId: { default: "" }, alt: { default: "" }, caption: { default: "" } };
  },

  parseHTML() {
    return [{
      tag: "span[data-picture]",
      getAttrs: (element) => ({
        fileId: (element as HTMLElement).getAttribute("data-picture") ?? "",
        alt: (element as HTMLElement).getAttribute("data-alt") ?? "",
        caption: (element as HTMLElement).getAttribute("data-caption") ?? "",
      }),
    }];
  },

  renderHTML({ node, HTMLAttributes }) {
    return ["span", mergeAttributes(HTMLAttributes, {
      "data-picture": node.attrs.fileId, "data-alt": node.attrs.alt, "data-caption": node.attrs.caption,
    }), String(node.attrs.alt)];
  },

  markdownTokenName: "picture",

  markdownTokenizer: {
    name: "picture",
    level: "inline",
    start: (src: string) => src.indexOf("!["),
    tokenize: (src: string) => {
      const found = PICTURE_START.exec(src);
      if (!found) return undefined;
      return { type: "picture", raw: found[0], fileId: found[2], alt: unescapeLine(found[1]), caption: unescapeLine(found[3] ?? "") };
    },
  },

  parseMarkdown: (token) => ({
    type: "picture",
    attrs: {
      fileId: String((token as { fileId?: string }).fileId ?? ""),
      alt: String((token as { alt?: string }).alt ?? ""),
      caption: String((token as { caption?: string }).caption ?? ""),
    },
  }),

  renderMarkdown: (node) => pictureMarkdown(String(node.attrs?.fileId ?? ""), String(node.attrs?.alt ?? ""), String(node.attrs?.caption ?? "")),
});

/**
 * Puts a picture in the document as a paragraph of its own (so a report prints it as a figure): in place when the cursor is
 * in an empty paragraph, else after the top-level block the cursor is in.
 *
 * @param editor The editor, which must have `PictureNode`.
 * @param choice The attachment's file id and the picture's alternative text and caption.
 */
export function insertPicture(editor: Editor, choice: { fileId: string; alt: string; caption: string }): void {
  const node = { type: "picture", attrs: choice };
  const { $from } = editor.state.selection;
  const inEmptyParagraph = $from.parent.type.name === "paragraph" && $from.parent.content.size === 0 && $from.depth === 1;
  if (inEmptyParagraph) {
    editor.chain().focus().insertContent(node).run();
    return;
  }
  const position = $from.depth >= 1 ? $from.after(1) : editor.state.doc.content.size;
  editor.chain().focus().insertContentAt(position, { type: "paragraph", content: [node] }).run();
}
