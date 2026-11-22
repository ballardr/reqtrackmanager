/**
 * Module: components/VisualMarkdownEditor
 *
 * The Visual view of a Markdown field: an editable document (TipTap) over the same Markdown source the Write view
 * edits, with the shared formatting toolbar, tables, code and Mermaid diagrams drawn beside their source.
 *
 * Responsibilities:
 * - Read the field's Markdown into the editor and report Markdown through `onChange` after an edit; opening a text
 *   never writes it back.
 * - Refuse a text the editor cannot hold without changing it (`findVisualBlocker`) by reporting the reason through
 *   `onBlocked` and drawing nothing, so the field falls back to Write.
 * - Offer to convert pasted text that looks like Markdown (a notice under the toolbar: Convert to formatting, or
 *   Keep as typed), replacing only the pasted range.
 * - Show the toolbar only while focus is inside the field (`ActiveFieldFrame`; the Markdown editor's frame when nested).
 * - Draw a `mermaid` code block as an editable source with a live diagram beneath it.
 * - In a field that holds mathematics (`math`), draw each equation as an equation; pressing one opens the same panel
 *   the toolbar's equation buttons use, with a live preview, to change its TeX.
 *
 * Design decisions:
 * - Edits are reported after a short pause and on blur and close, because writing Markdown for a long document is
 *   not free; the value the parent holds is always what the editor last wrote.
 * - A value that changes from outside while the editor is open (not one this editor reported) replaces the
 *   content, so a form reset or a restored draft shows.
 * - Pasted HTML (from a web page or a word processor) is reduced by the editor's schema as before; only plain text
 *   that looks like Markdown gets the conversion notice, since that is the text that arrives as literal symbols.
 *
 * Dependencies: TipTap, `utils/visualMarkdown`, `utils/visualMathNode`, `RichTextToolbar`, `MermaidDiagram`,
 * `MathEditPopover`, `MathEquation` (loaded on first use).
 */
import { EditorContent, NodeViewContent, NodeViewWrapper, ReactNodeViewRenderer, useEditor, type Editor, type NodeViewProps } from "@tiptap/react";
import { lazy, Suspense, useEffect, useMemo, useRef, useState, type KeyboardEvent, type TextareaHTMLAttributes } from "react";

import { useStrings } from "../context/TerminologyContext";
import {
  findVisualBlocker, looksLikeMarkdown, MarkdownCodeBlock, roundTripMarkdown, visualMarkdownExtensions, writtenMarkdown,
  type VisualBlocker,
} from "../utils/visualMarkdown";
import { equationMarkdown, MathNode } from "../utils/visualMathNode";
import { ActiveFieldFrame, ActiveFieldToolbar } from "./ActiveFieldFrame";
import { MathEditPopover } from "./MathEditPopover";
import { MermaidDiagram } from "./MermaidDiagram";
import { RichTextToolbar } from "./RichTextToolbar";

const MathEquation = lazy(() => import("./MathEquation").then((module) => ({ default: module.MathEquation })));

const EMIT_DELAY_MS = 150;
const DIAGRAM_DELAY_MS = 500;

/** The text after it has stopped changing for `delay` milliseconds. */
function useSettled(value: string, delay: number): string {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return settled;
}

function DiagramBlock({ source }: { source: string }) {
  const text = useStrings().richText;
  const settled = useSettled(source, DIAGRAM_DELAY_MS);
  return (
    <NodeViewWrapper className="visual-diagram-block">
      <div className="text-muted" contentEditable={false} style={{ fontSize: "0.85rem" }}>{text.diagramSourceLabel}</div>
      <pre><NodeViewContent className="visual-code" /></pre>
      <div contentEditable={false}><MermaidDiagram source={settled} showSource={false} /></div>
    </NodeViewWrapper>
  );
}

function CodeBlockView({ node }: NodeViewProps) {
  if (node.attrs.language === "mermaid") return <DiagramBlock source={node.textContent} />;
  return <NodeViewWrapper as="pre"><NodeViewContent className="visual-code" /></NodeViewWrapper>;
}

const VisualCodeBlock = MarkdownCodeBlock.extend({
  addNodeView() {
    return ReactNodeViewRenderer(CodeBlockView);
  },
});

/** An equation in the document: drawn as an equation, and changed in the equation panel when pressed. */
function MathView({ node, updateAttributes, selected, editor }: NodeViewProps) {
  const text = useStrings().richText;
  const anchor = useRef<HTMLSpanElement>(null);
  const [changing, setChanging] = useState(false);
  const tex = String(node.attrs.tex);
  const display = Boolean(node.attrs.display);
  const open = () => { if (editor.isEditable) setChanging(true); };
  function onKeyDown(event: KeyboardEvent) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      open();
    }
  }
  return (
    <NodeViewWrapper as="span" className={`visual-math${display ? " visual-math--display" : ""}${selected ? " is-selected" : ""}`}>
      <span
        ref={anchor} role="button" tabIndex={0} contentEditable={false} className="visual-math__equation"
        aria-label={`${text.mathChange}: ${tex}`} aria-haspopup="dialog" aria-expanded={changing} onClick={open} onKeyDown={onKeyDown}
      >
        <Suspense fallback={<>{equationMarkdown(tex, display)}</>}><MathEquation tex={tex} display={display} /></Suspense>
      </span>
      {changing && (
        <MathEditPopover
          anchorRef={anchor} display={display} initialTex={tex} changing onClose={() => setChanging(false)}
          onApply={(next) => { setChanging(false); updateAttributes({ tex: next }); }}
        />
      )}
    </NodeViewWrapper>
  );
}

const VisualMathNode = MathNode.extend({
  addNodeView() {
    return ReactNodeViewRenderer(MathView);
  },
});

interface PastedRange {
  from: number;
  to: number;
  text: string;
}

type TextAreaExtras = Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "value" | "onChange" | "rows" | "className" | "style">;

/**
 * @param value The Markdown source.
 * @param onChange Called with the Markdown after an edit.
 * @param onBlocked Called once, on opening, with the reason the text cannot be edited visually.
 * @param rows Minimum visible lines (sets the minimum height).
 * @param ariaLabel The editable area's accessible name.
 * @param disabled Whether editing is unavailable.
 * @param textareaProps Attributes shared with the Write view (id, required) applied to the editable area.
 * @param math Whether the field holds mathematics: equations are drawn as equations and the toolbar offers them.
 */
export function VisualMarkdownEditor({ value, onChange, onBlocked, rows = 4, ariaLabel, disabled, textareaProps, math }: {
  value: string;
  onChange: (value: string) => void;
  onBlocked: (reason: VisualBlocker) => void;
  rows?: number;
  ariaLabel: string;
  disabled?: boolean;
  textareaProps?: TextAreaExtras;
  math?: boolean;
}) {
  const text = useStrings().richText;
  const [initial] = useState(value);
  const lastReported = useRef(value);
  /** What the editor last wrote (or, before an edit, wrote on opening); only a change from it is reported. */
  const lastWritten = useRef<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingPaste = useRef<{ from: number; removed: number; sizeBefore: number; text: string } | null>(null);
  const [pasted, setPasted] = useState<PastedRange | null>(null);
  const live = useRef<Editor | null>(null);
  const report = useRef(onChange);
  useEffect(() => { report.current = onChange; }, [onChange]);

  const extensions = useMemo(() => visualMarkdownExtensions(VisualCodeBlock, math ? VisualMathNode : null), [math]);
  const editor = useEditor({
    extensions,
    content: initial,
    contentType: "markdown",
    editable: !disabled,
    editorProps: {
      attributes: {
        ...(textareaProps?.id ? { id: textareaProps.id } : {}), role: "textbox", "aria-multiline": "true", "aria-label": ariaLabel,
        ...(textareaProps?.required ? { "aria-required": "true" } : {}),
        class: "visual-markdown-content markdown-view",
        style: `min-height: ${Math.max(rows, 3) * 1.6}em`,
      },
      handlePaste: (view, event) => {
        const data = event.clipboardData;
        const plain = data?.getData("text/plain") ?? "";
        if (data && !data.getData("text/html") && looksLikeMarkdown(plain)) {
          const { from, to } = view.state.selection;
          pendingPaste.current = { from, removed: to - from, sizeBefore: view.state.doc.content.size, text: plain };
          setTimeout(() => { pendingPaste.current = null; }, 0);
        }
        return false;
      },
    },
    onUpdate: ({ editor: e }) => {
      const paste = pendingPaste.current;
      pendingPaste.current = null;
      if (paste && findVisualBlocker(paste.text, roundTripMarkdown(paste.text, math), math) === null) {
        const inserted = e.state.doc.content.size - (paste.sizeBefore - paste.removed);
        setPasted({ from: paste.from, to: paste.from + inserted, text: paste.text });
      } else {
        setPasted(null);
      }
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => flush(e), EMIT_DELAY_MS);
    },
    onBlur: ({ editor: e }) => flush(e),
    // The editor still holds its content while it emits `destroy`, so a pending edit is reported before it closes.
    onDestroy: () => {
      if (live.current && timer.current) flush(live.current);
    },
  });
  useEffect(() => { live.current = editor; }, [editor]);

  /** Reports the editor's Markdown when it differs from what the parent last received. */
  function flush(e: NonNullable<typeof editor>) {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    if (e.isDestroyed) return;
    const next = writtenMarkdown(e);
    if (next !== lastWritten.current) {
      lastWritten.current = next;
      lastReported.current = next;
      report.current(next);
    }
  }

  // What the editor writes for the text as opened: the baseline an edit is measured against.
  const opened = useMemo(() => (editor ? writtenMarkdown(editor) : null), [editor]);
  const blocker = useMemo(() => (opened === null ? null : findVisualBlocker(initial, opened, math)), [opened, initial, math]);
  useEffect(() => { lastWritten.current = opened; }, [opened]);
  useEffect(() => {
    if (blocker) onBlocked(blocker);
  }, [blocker, onBlocked]);

  // A value that did not come from this editor replaces the content.
  useEffect(() => {
    if (!editor || editor.isDestroyed || value === lastReported.current) return;
    lastReported.current = value;
    editor.commands.setContent(value, { contentType: "markdown", emitUpdate: false });
    lastWritten.current = writtenMarkdown(editor);
  }, [value, editor]);

  useEffect(() => { editor?.setEditable(!disabled); }, [editor, disabled]);

  function convertPasted() {
    if (!editor || !pasted) return;
    const { doc } = editor.state;
    let { from, to } = pasted;
    const start = doc.resolve(Math.min(from, doc.content.size));
    const end = doc.resolve(Math.min(to, doc.content.size));
    // A paste that fills whole paragraphs replaces them, so no empty paragraph is left behind.
    if (start.parentOffset === 0 && end.parentOffset === end.parent.content.size && start.depth > 0) {
      from = start.before();
      to = end.after();
    }
    editor.chain().focus().insertContentAt({ from, to }, pasted.text, { contentType: "markdown" }).run();
    setPasted(null);
  }

  if (!editor || blocker) return null;
  return (
    <ActiveFieldFrame className="stack" style={{ gap: "var(--space-1)" }}>
      <ActiveFieldToolbar>
        <RichTextToolbar editor={editor} features={{ code: true, codeBlock: true, table: true, diagram: true, math }} disabled={disabled} />
      </ActiveFieldToolbar>
      {pasted && (
        <div className="row" role="status" style={{ flexWrap: "wrap", gap: "var(--space-2)", alignItems: "center" }}>
          <span>{text.pastedMarkdown}</span>
          <button type="button" className="btn btn-primary" onClick={convertPasted}>{text.pasteConvert}</button>
          <button type="button" className="btn" onClick={() => setPasted(null)}>{text.pasteKeep}</button>
        </div>
      )}
      <div className="policy-editor visual-markdown-editor">
        <EditorContent editor={editor} />
      </div>
    </ActiveFieldFrame>
  );
}
