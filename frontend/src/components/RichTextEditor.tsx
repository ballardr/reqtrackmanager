import { Bold, Heading1, Heading2, Heading3, Italic, Link as LinkIcon, List } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { htmlToMarkdown, renderMarkdown } from "../utils/markdown";
import { Tooltip } from "./Tooltip";

type Mode = "markdown" | "rich";

/**
 * An editor for the app's Markdown subset (`utils/markdown.ts`) that can
 * be used as either plain Markdown or a WYSIWYG rich-text surface — the
 * same choice for every long-form text field in this app that ends up in
 * a generated report (project/organisation report intros and chapter
 * bodies). The underlying value is always Markdown, regardless of which
 * mode is currently active; switching modes converts in place
 * (`renderMarkdown`/`htmlToMarkdown`) rather than keeping two separate
 * representations that could drift apart.
 *
 * The rich-text side is a plain `contentEditable` + `document.execCommand`
 * toolbar (Bold/Italic/H1-H3/bullet list/link) — deliberately not a full
 * editor framework (no TipTap/Slate/Quill dependency): it only needs to
 * cover exactly the subset `utils/markdown.ts` already renders, the same
 * "match the supported subset, nothing more" choice already made twice in
 * this codebase (the Python PDF renderer, then this same TS renderer).
 * `execCommand` is deprecated but still broadly supported; documented as a
 * known constraint rather than silently relied on — see `docs/decisions.md`.
 *
 * The `contentEditable` div's HTML is only ever set imperatively when
 * *entering* rich mode (or on first mount in rich mode) — never re-synced
 * from `value` on every render — otherwise every keystroke's resulting
 * `onChange` -> parent re-render would reset the caret to the start of the
 * field, a classic controlled-`contentEditable` bug.
 */
export function RichTextEditor({
  value,
  onChange,
  rows = 3,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  placeholder?: string;
}) {
  const [mode, setMode] = useState<Mode>("markdown");
  const editableRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (mode === "rich" && editableRef.current) {
      editableRef.current.innerHTML = renderMarkdown(value);
    }
    // Deliberately only re-run when `mode` changes, not `value` — see the
    // docstring above on why the contentEditable content isn't re-synced
    // from `value` on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  function switchMode(next: Mode) {
    if (next === mode) return;
    if (next === "markdown" && editableRef.current) {
      // Leaving rich mode: capture whatever's currently in the DOM before
      // the contentEditable unmounts.
      onChange(htmlToMarkdown(editableRef.current));
    }
    setMode(next);
  }

  function handleRichInput() {
    if (editableRef.current) onChange(htmlToMarkdown(editableRef.current));
  }

  function exec(command: string, arg?: string) {
    editableRef.current?.focus();
    document.execCommand(command, false, arg);
    handleRichInput();
  }

  function insertLink() {
    const url = window.prompt("Link URL");
    if (url) exec("createLink", url);
  }

  return (
    <div className="stack" style={{ gap: "0.3rem" }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="row" style={{ gap: 0 }}>
          <button
            type="button"
            className={`btn${mode === "markdown" ? " btn-primary" : ""}`}
            style={{ borderRadius: "6px 0 0 6px" }}
            onClick={() => switchMode("markdown")}
          >
            Markdown
          </button>
          <button
            type="button"
            className={`btn${mode === "rich" ? " btn-primary" : ""}`}
            style={{ borderRadius: "0 6px 6px 0", marginLeft: -1 }}
            onClick={() => switchMode("rich")}
          >
            Rich text
          </button>
        </div>
        {mode === "rich" && (
          <div className="row" style={{ gap: "0.25rem" }}>
            <Tooltip label="Bold">
              <button type="button" className="btn" aria-label="Bold" onClick={() => exec("bold")}>
                <Bold size={14} />
              </button>
            </Tooltip>
            <Tooltip label="Italic">
              <button type="button" className="btn" aria-label="Italic" onClick={() => exec("italic")}>
                <Italic size={14} />
              </button>
            </Tooltip>
            <Tooltip label="Heading 1">
              <button type="button" className="btn" aria-label="Heading 1" onClick={() => exec("formatBlock", "h1")}>
                <Heading1 size={14} />
              </button>
            </Tooltip>
            <Tooltip label="Heading 2">
              <button type="button" className="btn" aria-label="Heading 2" onClick={() => exec("formatBlock", "h2")}>
                <Heading2 size={14} />
              </button>
            </Tooltip>
            <Tooltip label="Heading 3">
              <button type="button" className="btn" aria-label="Heading 3" onClick={() => exec("formatBlock", "h3")}>
                <Heading3 size={14} />
              </button>
            </Tooltip>
            <Tooltip label="Bullet list">
              <button
                type="button" className="btn" aria-label="Bullet list"
                onClick={() => exec("insertUnorderedList")}
              >
                <List size={14} />
              </button>
            </Tooltip>
            <Tooltip label="Link">
              <button type="button" className="btn" aria-label="Link" onClick={insertLink}>
                <LinkIcon size={14} />
              </button>
            </Tooltip>
          </div>
        )}
      </div>
      {mode === "markdown" ? (
        <textarea
          className="input"
          rows={rows}
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <div
          ref={editableRef}
          className="input rich-text-editable"
          contentEditable
          onInput={handleRichInput}
          style={{ minHeight: `${rows * 1.6}em` }}
        />
      )}
    </div>
  );
}
