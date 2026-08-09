import { Bold, Heading1, Heading2, Heading3, Image as ImageIcon, Italic, Link as LinkIcon, List } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import type { FileAsset } from "../api/types";
import { htmlToMarkdown, renderMarkdown, resolveImageRef } from "../utils/markdown";
import { Tooltip } from "./Tooltip";

type Mode = "markdown" | "rich";

/**
 * An editor for the app's Markdown subset (`utils/markdown.ts`) that can
 * be used as either plain Markdown or a WYSIWYG rich-text surface — the
 * same choice for every long-form text field in this app that ends up in
 * a generated report (project/organisation report intros and chapter
 * bodies, report templates). The underlying value is always Markdown,
 * regardless of which mode is currently active; switching modes converts
 * in place (`renderMarkdown`/`htmlToMarkdown`) rather than keeping two
 * separate representations that could drift apart.
 *
 * The rich-text side is a plain `contentEditable` + `document.execCommand`
 * toolbar (Bold/Italic/H1-H3/bullet list/link/image) — deliberately not a
 * full editor framework (no TipTap/Slate/Quill dependency): it only needs
 * to cover exactly the subset `utils/markdown.ts` already renders, the
 * same "match the supported subset, nothing more" choice already made
 * twice in this codebase (the Python PDF renderer, then this same TS
 * renderer). `execCommand` is deprecated but still broadly supported;
 * documented as a known constraint rather than silently relied on — see
 * `docs/decisions.md`.
 *
 * The `contentEditable` div's HTML is only ever set imperatively when
 * *entering* rich mode (or on first mount in rich mode) — never re-synced
 * from `value` on every render — otherwise every keystroke's resulting
 * `onChange` -> parent re-render would reset the caret to the start of the
 * field, a classic controlled-`contentEditable` bug.
 *
 * `organizationId`, when provided, enables the "Insert image" toolbar
 * button: a picker over that org's existing shared resources (filtered to
 * image content types) plus an inline upload shortcut, reusing the
 * existing org-resource upload endpoint rather than a dedicated one —
 * report images are just shared-resource images. Selecting one inserts
 * `![filename](attachment:<file id>)` — a reference resolved server-side
 * at PDF-generation time and client-side (`resolveImageRef`) for preview,
 * never a raw fetchable URL (see `utils/markdown.ts`'s module docstring
 * for why). Omitting `organizationId` simply hides the button — every
 * existing caller keeps working unchanged.
 */
export function RichTextEditor({
  value,
  onChange,
  rows = 3,
  placeholder,
  organizationId,
}: {
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  placeholder?: string;
  organizationId?: string;
}) {
  const [mode, setMode] = useState<Mode>("markdown");
  const editableRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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

  function insertMarkdownAtCursor(text: string) {
    const textarea = textareaRef.current;
    if (!textarea) {
      onChange(`${value}\n\n${text}\n`);
      return;
    }
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const before = value.slice(0, start);
    const after = value.slice(end);
    // A blank line on each side keeps it as its own paragraph, matching
    // both this app's own report-chapter Markdown and the backend PDF
    // renderer's expectation that an image reference is a paragraph on
    // its own (see services/reports.py::_markdown_to_flowables).
    const needsLeadingBreak = before.length > 0 && !before.endsWith("\n\n");
    const insertion = `${needsLeadingBreak ? "\n\n" : ""}${text}\n\n`;
    onChange(`${before}${insertion}${after}`);
    requestAnimationFrame(() => {
      textarea.focus();
      const pos = before.length + insertion.length;
      textarea.setSelectionRange(pos, pos);
    });
  }

  function insertImage(asset: FileAsset) {
    const ref = `attachment:${asset.id}`;
    if (mode === "markdown") {
      insertMarkdownAtCursor(`![${asset.filename}](${ref})`);
    } else {
      const url = resolveImageRef(ref);
      editableRef.current?.focus();
      document.execCommand("insertHTML", false, `<img src="${url}" alt="${asset.filename}" style="max-width:100%">`);
      handleRichInput();
    }
    setImagePickerOpen(false);
  }

  const [imagePickerOpen, setImagePickerOpen] = useState(false);
  const [orgImages, setOrgImages] = useState<FileAsset[] | null>(null);
  const [imagePickerError, setImagePickerError] = useState<string | null>(null);
  const [uploadingImage, setUploadingImage] = useState(false);

  async function openImagePicker() {
    setImagePickerOpen(true);
    if (!organizationId || orgImages !== null) return;
    try {
      const resources = await api.get<FileAsset[]>(`/api/v1/orgs/${organizationId}/resources`);
      setOrgImages(resources.filter((r) => r.content_type.startsWith("image/")));
    } catch (err) {
      setImagePickerError(err instanceof Error ? err.message : "Could not load images.");
    }
  }

  async function uploadImage(file: File) {
    if (!organizationId) return;
    setImagePickerError(null);
    setUploadingImage(true);
    try {
      const asset = await api.postFile<FileAsset>(`/api/v1/orgs/${organizationId}/resources`, file);
      setOrgImages((current) => [...(current ?? []), asset]);
      insertImage(asset);
    } catch (err) {
      setImagePickerError(err instanceof Error ? err.message : "Could not upload image.");
    } finally {
      setUploadingImage(false);
    }
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
        <div className="row" style={{ gap: "0.25rem" }}>
          {organizationId && (
            <Tooltip label="Insert image">
              <button type="button" className="btn" aria-label="Insert image" onClick={openImagePicker}>
                <ImageIcon size={14} />
              </button>
            </Tooltip>
          )}
          {mode === "rich" && (
            <>
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
            </>
          )}
        </div>
      </div>
      {imagePickerOpen && (
        <div className="card stack" style={{ padding: "0.5rem" }}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <strong style={{ fontSize: "0.85rem" }}>Insert image</strong>
            <button type="button" className="btn" onClick={() => setImagePickerOpen(false)}>
              Close
            </button>
          </div>
          {imagePickerError && <div style={{ color: "var(--color-danger)" }}>{imagePickerError}</div>}
          {orgImages === null ? (
            <span className="text-muted">Loading…</span>
          ) : orgImages.length === 0 ? (
            <span className="text-muted">No images uploaded to this organisation yet.</span>
          ) : (
            <div className="row" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
              {orgImages.map((img) => (
                <button
                  key={img.id}
                  type="button"
                  className="btn"
                  style={{ padding: "0.25rem", flexDirection: "column", height: "auto" }}
                  title={img.filename}
                  onClick={() => insertImage(img)}
                >
                  <img
                    src={resolveImageRef(`attachment:${img.id}`) ?? ""}
                    alt={img.filename}
                    style={{ width: 64, height: 64, objectFit: "cover", borderRadius: 4 }}
                  />
                  <span style={{ fontSize: "0.7rem", maxWidth: 64, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {img.filename}
                  </span>
                </button>
              ))}
            </div>
          )}
          <label className="stack" style={{ gap: "0.25rem" }}>
            <span className="text-muted" style={{ fontSize: "0.8rem" }}>Or upload a new image</span>
            <input
              type="file"
              accept="image/*"
              disabled={uploadingImage}
              onChange={(e) => e.target.files?.[0] && uploadImage(e.target.files[0])}
            />
          </label>
        </div>
      )}
      {mode === "markdown" ? (
        <textarea
          ref={textareaRef}
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
