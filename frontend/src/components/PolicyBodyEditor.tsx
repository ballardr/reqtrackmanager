/**
 * Module: components/PolicyBodyEditor
 *
 * The visual editor for a policy body: a toolbar over an editable document (TipTap), limited to the vocabulary the
 * server accepts (headings 1 to 3, paragraphs, bulleted and numbered lists, quotations, horizontal rule, bold,
 * italic and links). It reports the document as JSON through `onChange`; the server validates it again.
 *
 * Design decisions:
 * - The extension set is the server's vocabulary and nothing wider (code, strike-through, underline and code
 *   blocks are off), so what is typed or pasted can always be saved. Pasted content outside it is reduced by the
 *   editor's schema to the nearest allowed node.
 * - A link takes only https, http or mailto addresses (`isAllowedUri`), matching the server's rule; it is edited in
 *   a field under the toolbar rather than a browser prompt. With no text selected, the address becomes the link text.
 * - The initial `value` seeds the editor; later `value` changes from the parent are not pushed back in (the editor
 *   owns the text while open), so a dialog mounts one editor per policy.
 */
import { EditorContent, useEditor, useEditorState, type Editor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import {
  Bold, Heading1, Heading2, Heading3, Italic, Link2, List, ListOrdered, Minus, Quote, Redo2, Undo2, Unlink,
  type LucideIcon,
} from "lucide-react";
import { useId, useState } from "react";

import type { PolicyBody } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { FieldCaption } from "./FieldHelp";
import { Tooltip } from "./Tooltip";

const ALLOWED_LINK = /^(https?:|mailto:)/i;

function ToolbarButton({ icon: Icon, label, active, disabled, onClick }: {
  icon: LucideIcon; label: string; active?: boolean; disabled?: boolean; onClick: () => void;
}) {
  return (
    <Tooltip label={label}>
      <button
        type="button" className={`btn ${active ? "btn-primary" : ""}`} aria-label={label} aria-pressed={active}
        disabled={disabled} onClick={onClick}
      >
        <Icon size={16} />
      </button>
    </Tooltip>
  );
}

function Toolbar({ editor }: { editor: Editor }) {
  const text = useStrings().policies;
  const [linkOpen, setLinkOpen] = useState(false);
  const [address, setAddress] = useState("");
  const [invalid, setInvalid] = useState(false);
  const state = useEditorState({
    editor,
    selector: ({ editor: e }) => ({
      bold: e.isActive("bold"), italic: e.isActive("italic"), h1: e.isActive("heading", { level: 1 }),
      h2: e.isActive("heading", { level: 2 }), h3: e.isActive("heading", { level: 3 }), bullet: e.isActive("bulletList"),
      ordered: e.isActive("orderedList"), quote: e.isActive("blockquote"), link: e.isActive("link"),
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
    const href = address.trim();
    if (!ALLOWED_LINK.test(href)) {
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

  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      <div className="row policy-editor-toolbar" role="toolbar" aria-label={text.toolbar} style={{ flexWrap: "wrap", gap: "var(--space-1)" }}>
        <ToolbarButton icon={Bold} label={text.bold} active={state.bold} onClick={() => chain().toggleBold().run()} />
        <ToolbarButton icon={Italic} label={text.italic} active={state.italic} onClick={() => chain().toggleItalic().run()} />
        <ToolbarButton icon={Heading1} label={text.heading1} active={state.h1} onClick={() => chain().toggleHeading({ level: 1 }).run()} />
        <ToolbarButton icon={Heading2} label={text.heading2} active={state.h2} onClick={() => chain().toggleHeading({ level: 2 }).run()} />
        <ToolbarButton icon={Heading3} label={text.heading3} active={state.h3} onClick={() => chain().toggleHeading({ level: 3 }).run()} />
        <ToolbarButton icon={List} label={text.bulletList} active={state.bullet} onClick={() => chain().toggleBulletList().run()} />
        <ToolbarButton icon={ListOrdered} label={text.orderedList} active={state.ordered} onClick={() => chain().toggleOrderedList().run()} />
        <ToolbarButton icon={Quote} label={text.quote} active={state.quote} onClick={() => chain().toggleBlockquote().run()} />
        <ToolbarButton icon={Minus} label={text.rule} onClick={() => chain().setHorizontalRule().run()} />
        <ToolbarButton icon={Link2} label={text.link} active={state.link} onClick={openLink} />
        {state.link && <ToolbarButton icon={Unlink} label={text.linkRemove} onClick={() => chain().extendMarkRange("link").unsetLink().run()} />}
        <ToolbarButton icon={Undo2} label={text.undo} disabled={!state.canUndo} onClick={() => chain().undo().run()} />
        <ToolbarButton icon={Redo2} label={text.redo} disabled={!state.canRedo} onClick={() => chain().redo().run()} />
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

/**
 * @param label The visible caption (also the editable area's accessible name).
 * @param value The document the editor starts with.
 * @param onChange Called with the document after every edit.
 * @param help Help text for the caption's (?) button.
 */
export function PolicyBodyEditor({ label, value, onChange, help }: {
  label: string; value: PolicyBody; onChange: (body: PolicyBody) => void; help?: string;
}) {
  const id = useId();
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        code: false, codeBlock: false, strike: false, underline: false,
        heading: { levels: [1, 2, 3] },
        link: {
          openOnClick: false, autolink: false, linkOnPaste: true,
          isAllowedUri: (url) => ALLOWED_LINK.test(url),
          HTMLAttributes: { rel: "noopener noreferrer", target: "_blank" },
        },
      }),
    ],
    content: value.content.length > 0 ? value : undefined,
    editorProps: { attributes: { id, role: "textbox", "aria-multiline": "true", "aria-label": label, class: "policy-editor-content policy-body" } },
    onUpdate: ({ editor: e }) => onChange(e.getJSON() as PolicyBody),
  });

  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      <FieldCaption label={label} help={help} htmlFor={id} />
      {editor && <Toolbar editor={editor} />}
      <div className="policy-editor">
        <EditorContent editor={editor} />
      </div>
    </div>
  );
}
