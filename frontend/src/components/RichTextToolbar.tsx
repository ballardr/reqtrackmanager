/**
 * Module: components/RichTextToolbar
 *
 * The formatting toolbar over a TipTap editor, shared by the policy editor and the visual Markdown editor.
 *
 * Responsibilities:
 * - Offer the marks and blocks every rich text field has (bold, italic, headings 1 to 3, lists, quotation, rule,
 *   link, undo, redo), each shown pressed while it applies at the cursor.
 * - Offer the extras a field opts into through `features`: inline code, code block, table (with row and column
 *   actions while the cursor is in one), diagram, equations (Inline equation and Equation block) and a picture of the
 *   record's own attachment (`PictureToolbarButton`, shown only inside a record page that supplies pictures).
 * - Edit a link in a field under the toolbar rather than a browser prompt, accepting https, http and mailto only.
 *
 * Design decisions:
 * - The buttons are the small size and grouped (text, headings, blocks, insert, history) with a separator between
 *   groups, so the toolbar takes one short row; it wraps rather than hiding any button behind a menu, because a
 *   narrow field is the only case that needs more than one row.
 * - The toolbar only issues commands the editor's extensions define, so a field offers a button only when its
 *   editor was built with the matching extension (`features` must agree with the extension set).
 * - Whitespace in a link address is encoded (`%20`) so the stored Markdown link stays valid.
 *
 * Dependencies: TipTap, lucide icons, `ToolbarButton`.
 */
import type { Editor } from "@tiptap/react";
import { useEditorState } from "@tiptap/react";
import {
  BetweenHorizontalEnd, BetweenVerticalEnd, Bold, Code, Columns3, Heading1, Heading2, Heading3, Italic, Link2, List, ListOrdered,
  Minus, Quote, Redo2, Rows3, SquareCode, Table, Trash2, Undo2, Unlink, Workflow,
} from "lucide-react";
import { useState } from "react";

import { useStrings } from "../context/TerminologyContext";
import { SAFE_LINK } from "../utils/markdownIt";
import { DIAGRAM_TEMPLATE } from "../utils/markdownEdit";
import { insertPicture } from "../utils/visualImageNode";
import { MathToolbarButton } from "./MathEditPopover";
import { PictureToolbarButton } from "./PicturePicker";
import { ToolbarButton } from "./ToolbarButton";

/** The optional parts of the toolbar; each needs the matching extension in the editor. */
export interface RichTextFeatures {
  code?: boolean;
  codeBlock?: boolean;
  table?: boolean;
  diagram?: boolean;
  /** Equations; the editor must have the equation node (`utils/visualMathNode`). */
  math?: boolean;
  /** Pictures; the editor must have the picture node (`utils/visualImageNode`). */
  picture?: boolean;
}

/**
 * @param editor The editor the toolbar commands apply to.
 * @param features Optional parts to show.
 * @param disabled Whether editing is unavailable.
 */
export function RichTextToolbar({ editor, features = {}, disabled }: { editor: Editor; features?: RichTextFeatures; disabled?: boolean }) {
  const text = useStrings().richText;
  const [linkOpen, setLinkOpen] = useState(false);
  const [address, setAddress] = useState("");
  const [invalid, setInvalid] = useState(false);
  const state = useEditorState({
    editor,
    selector: ({ editor: e }) => ({
      bold: e.isActive("bold"), italic: e.isActive("italic"), h1: e.isActive("heading", { level: 1 }),
      h2: e.isActive("heading", { level: 2 }), h3: e.isActive("heading", { level: 3 }), bullet: e.isActive("bulletList"),
      ordered: e.isActive("orderedList"), quote: e.isActive("blockquote"), link: e.isActive("link"),
      code: e.isActive("code"), codeBlock: e.isActive("codeBlock"), inTable: e.isActive("table"),
      canUndo: e.can().undo(), canRedo: e.can().redo(),
    }),
  });
  const chain = () => editor.chain().focus();

  function openLink() {
    setAddress((editor.getAttributes("link").href as string | undefined) ?? "");
    setInvalid(false);
    setLinkOpen(true);
  }

  function applyLink() {
    const href = address.trim().replace(/\s/g, "%20");
    if (!SAFE_LINK.test(href)) {
      setInvalid(true);
      return;
    }
    if (editor.state.selection.empty && !editor.isActive("link")) {
      // Nothing is selected to turn into a link, so the address itself becomes the linked text.
      chain().insertContent({ type: "text", text: href, marks: [{ type: "link", attrs: { href } }] }).run();
    } else {
      chain().extendMarkRange("link").setLink({ href }).run();
    }
    setLinkOpen(false);
  }

  const button = (icon: typeof Bold, label: string, run: () => void, active?: boolean, off?: boolean) => (
    <ToolbarButton icon={icon} label={label} active={active} disabled={disabled || off} onClick={run} />
  );

  const separator = <span className="toolbar-divider" role="separator" aria-orientation="vertical" />;
  const selectedText = () => editor.state.doc.textBetween(editor.state.selection.from, editor.state.selection.to, " ");
  const insertMath = (tex: string, display: boolean) => chain().insertContent({ type: "math", attrs: { tex, display } }).run();

  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      <div className="row policy-editor-toolbar editor-toolbar" role="toolbar" aria-label={text.toolbar} style={{ flexWrap: "wrap", gap: "var(--space-1)", alignItems: "center" }}>
        {button(Bold, text.bold, () => chain().toggleBold().run(), state.bold)}
        {button(Italic, text.italic, () => chain().toggleItalic().run(), state.italic)}
        {features.code && button(Code, text.code, () => chain().toggleCode().run(), state.code)}
        {separator}
        {button(Heading1, text.heading1, () => chain().toggleHeading({ level: 1 }).run(), state.h1)}
        {button(Heading2, text.heading2, () => chain().toggleHeading({ level: 2 }).run(), state.h2)}
        {button(Heading3, text.heading3, () => chain().toggleHeading({ level: 3 }).run(), state.h3)}
        {separator}
        {button(List, text.bulletList, () => chain().toggleBulletList().run(), state.bullet)}
        {button(ListOrdered, text.orderedList, () => chain().toggleOrderedList().run(), state.ordered)}
        {button(Quote, text.quote, () => chain().toggleBlockquote().run(), state.quote)}
        {features.codeBlock && button(SquareCode, text.codeBlock, () => chain().toggleCodeBlock().run(), state.codeBlock)}
        {button(Minus, text.rule, () => chain().setHorizontalRule().run())}
        {separator}
        {button(Link2, text.link, openLink, state.link)}
        {state.link && button(Unlink, text.linkRemove, () => chain().extendMarkRange("link").unsetLink().run())}
        {features.table && button(Table, text.table, () => chain().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run(), state.inTable, state.inTable)}
        {features.table && state.inTable && (
          <>
            {button(BetweenHorizontalEnd, text.tableAddRow, () => chain().addRowAfter().run())}
            {button(BetweenVerticalEnd, text.tableAddColumn, () => chain().addColumnAfter().run())}
            {button(Rows3, text.tableDeleteRow, () => chain().deleteRow().run())}
            {button(Columns3, text.tableDeleteColumn, () => chain().deleteColumn().run())}
            {button(Trash2, text.tableDelete, () => chain().deleteTable().run())}
          </>
        )}
        {features.diagram && button(Workflow, text.diagram, () => chain().insertContent({ type: "codeBlock", attrs: { language: "mermaid" }, content: [{ type: "text", text: DIAGRAM_TEMPLATE }] }).run())}
        {features.math && (
          <>
            <MathToolbarButton display={false} readSelection={selectedText} onApply={insertMath} disabled={disabled} />
            <MathToolbarButton display readSelection={selectedText} onApply={insertMath} disabled={disabled} />
          </>
        )}
        {features.picture && <PictureToolbarButton disabled={disabled} onInsert={(choice) => insertPicture(editor, choice)} />}
        {separator}
        {button(Undo2, text.undo, () => chain().undo().run(), undefined, !state.canUndo)}
        {button(Redo2, text.redo, () => chain().redo().run(), undefined, !state.canRedo)}
      </div>
      {linkOpen && (
        <div className="row" style={{ alignItems: "flex-start" }}>
          <div className="stack" style={{ gap: "var(--space-1)", flex: 1 }}>
            <input
              className="input" type="url" aria-label={text.linkAddress} placeholder="https://" value={address} autoFocus
              aria-invalid={invalid || undefined}
              onChange={(e) => { setAddress(e.target.value); setInvalid(false); }}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); applyLink(); } }}
            />
            {invalid && <span style={{ color: "var(--color-danger)" }}>{text.linkInvalid}</span>}
          </div>
          <button type="button" className="btn btn-primary" onClick={applyLink}>{text.linkApply}</button>
        </div>
      )}
    </div>
  );
}
