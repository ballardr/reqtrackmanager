/**
 * Module: components/ReportLayoutRichTextToolbar
 *
 * The formatting buttons of the document view: bold, italic, code, link, bullet list and numbered list, for the text
 * under the caret.
 *
 * Responsibilities: apply each style or list kind to the current selection, show which ones the caret is in
 * (`aria-pressed`), and disable a button where the caret cannot take it (a heading holds no styles).
 *
 * Design decisions: these are the only formats the report engine draws, so they are the only ones offered; the
 * keyboard shortcuts of the editor (Ctrl/Cmd+B, I, E) and typing `**x**`, `*x*`, `` `x` ``, `- ` or `1. ` do the same.
 * A link needs selected words (or the caret in an existing link) and is made in a dialog that checks the address.
 */
import type { Editor } from "@tiptap/core";
import { useEditorState } from "@tiptap/react";
import { Bold, Code, Italic, Link, List, ListOrdered } from "lucide-react";
import { useState, type ReactElement } from "react";

import { useStrings } from "../context/TerminologyContext";
import { sectionsOf } from "../utils/reportLayoutDoc";
import { ReportLayoutLinkDialog } from "./ReportLayoutLinkDialog";
import { useRichText } from "./reportLayoutRichTextContext";

/**
 * @param editor The layout editor.
 * @param disabled Read-only: every button is off.
 */
export function ReportLayoutRichTextToolbar({ editor, disabled = false }: { editor: Editor; disabled?: boolean }) {
  const text = useStrings().reportOutline;
  const ctx = useRichText();
  const [linking, setLinking] = useState(false);
  const state = useEditorState({
    editor,
    selector: ({ editor: current }) => ({
      bold: current.isActive("bold"), canBold: current.can().toggleBold(),
      italic: current.isActive("italic"), canItalic: current.can().toggleItalic(),
      code: current.isActive("code"), canCode: current.can().toggleCode(),
      bullets: current.isActive("bulletList"), canBullets: current.can().toggleBulletList(),
      numbers: current.isActive("orderedList"), canNumbers: current.can().toggleOrderedList(),
      link: current.isActive("link"), canLink: current.can().setLink({ href: "https://example.org" }) && (!current.state.selection.empty || current.isActive("link")),
    }),
  });
  const button = (name: string, icon: ReactElement, pressed: boolean, can: boolean, run: () => void) => (
    <button
      type="button" className={`btn btn-sm btn-icon${pressed ? " btn-primary" : ""}`} aria-label={name} title={name} aria-pressed={pressed}
      disabled={disabled || !can} onMouseDown={(e) => e.preventDefault()} onClick={run}
    >
      {icon}
    </button>
  );
  return (
    <div className="row" role="toolbar" aria-label={text.formatLabel} style={{ gap: "var(--space-1)" }}>
      {button(text.formatBold, <Bold aria-hidden="true" />, state.bold, state.canBold, () => editor.chain().focus().toggleBold().run())}
      {button(text.formatItalic, <Italic aria-hidden="true" />, state.italic, state.canItalic, () => editor.chain().focus().toggleItalic().run())}
      {button(text.formatCode, <Code aria-hidden="true" />, state.code, state.canCode, () => editor.chain().focus().toggleCode().run())}
      {button(text.formatLink, <Link aria-hidden="true" />, state.link, state.canLink, () => setLinking(true))}
      {button(text.formatBullets, <List aria-hidden="true" />, state.bullets, state.canBullets, () => editor.chain().focus().toggleBulletList().run())}
      {button(text.formatNumbers, <ListOrdered aria-hidden="true" />, state.numbers, state.canNumbers, () => editor.chain().focus().toggleOrderedList().run())}
      {linking && (
        <ReportLayoutLinkDialog
          initialHref={String(editor.getAttributes("link").href ?? "")}
          sections={sectionsOf(ctx.currentTree())}
          onClose={() => setLinking(false)}
          onApply={(href) => {
            editor.chain().focus().extendMarkRange("link").setLink({ href }).run();
            setLinking(false);
          }}
          onRemove={state.link ? () => {
            editor.chain().focus().extendMarkRange("link").unsetLink().run();
            setLinking(false);
          } : undefined}
        />
      )}
    </div>
  );
}
