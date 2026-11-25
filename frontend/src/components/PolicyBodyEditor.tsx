/**
 * Module: components/PolicyBodyEditor
 *
 * The visual editor for a policy body: a toolbar (shown only while focus is inside the field,
 * `ActiveFieldFrame`) over an editable document (TipTap), limited to the vocabulary the server accepts (headings 1
 * to 3, paragraphs, bulleted and numbered lists, quotations, horizontal rule, bold, italic and links). It reports
 * the document as JSON through `onChange`; the server validates it again.
 *
 * The extension set is the server's vocabulary and nothing wider, so what is typed or pasted can always be saved;
 * pasted content outside it is reduced by the schema to the nearest allowed node. A link takes only https, http or
 * mailto addresses (`isAllowedUri`) and is edited in a field by `RichTextToolbar` (shared with the visual Markdown
 * editor). The initial `value` seeds the editor; later changes from the parent are not pushed in (the editor owns
 * the text while open), so a dialog mounts one editor per policy.
 */
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { useId } from "react";

import type { PolicyBody } from "../api/types";
import { SAFE_LINK } from "../utils/markdownIt";
import { ActiveFieldFrame, ActiveFieldToolbar } from "./ActiveFieldFrame";
import { FieldCaption } from "./FieldHelp";
import { RichTextToolbar } from "./RichTextToolbar";

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
          isAllowedUri: (url) => SAFE_LINK.test(url),
          HTMLAttributes: { rel: "noopener noreferrer", target: "_blank" },
        },
      }),
    ],
    content: value.content.length > 0 ? value : undefined,
    editorProps: { attributes: { id, role: "textbox", "aria-multiline": "true", "aria-label": label, class: "policy-editor-content policy-body" } },
    onUpdate: ({ editor: e }) => onChange(e.getJSON() as PolicyBody),
  });

  return (
    <ActiveFieldFrame className="stack" style={{ gap: "var(--space-1)" }}>
      <FieldCaption label={label} help={help} htmlFor={id} />
      {editor && <ActiveFieldToolbar><RichTextToolbar editor={editor} /></ActiveFieldToolbar>}
      <div className="policy-editor">
        <EditorContent editor={editor} />
      </div>
    </ActiveFieldFrame>
  );
}
