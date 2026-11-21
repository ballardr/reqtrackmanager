/**
 * Module: components/MarkdownEditor
 *
 * The editing control for a Markdown field: a Visual view (formatted editing, `VisualMarkdownEditor`), a Write view
 * (the source, with a formatting toolbar) and a Preview view (the same rendering readers see, including diagrams).
 * It owns no value; the caller holds the text.
 *
 * Responsibilities:
 * - Show the formatting toolbar only while focus is inside the field (`ActiveFieldFrame`).
 * - Apply a toolbar action to the textarea's selection through `utils/markdownEdit` and restore the selection.
 * - Grow with the text like every long field (`AutoGrowTextarea`); `rows` is the minimum height.
 * - Switch between the views with the shared `Tabs`; Preview shows `MarkdownView`.
 * - Open in the person's remembered view (Visual unless they chose Write), and fall back to Write with a stated
 *   reason when the text cannot be edited visually without changing it.
 * - `simple` offers Write and Preview only (a comment box, which does not need a document editor); `math` does the
 *   same because the visual writer escapes the characters an equation needs, and draws equations in Preview.
 *
 * Design decisions:
 * - The stored value is always the Markdown source, so what the author sees in Write is what is saved.
 * - The visual editor is loaded on first use (`lazy`), so a form that never shows it does not download TipTap.
 * - Only a tab the person clicks is remembered; a fallback to Write, and Preview, are not.
 * - The textarea keeps the field's accessible name and id, so the shared field label, help and form tests treat it
 *   as the plain text field it replaces.
 */
import { Code, Heading2, Italic, Link2, List, ListOrdered, Quote, Table, Workflow, Bold } from "lucide-react";
import { lazy, memo, Suspense, useCallback, useEffect, useId, useRef, useState, type TextareaHTMLAttributes } from "react";

import { useStrings } from "../context/TerminologyContext";
import { useMarkdownEditorView } from "../hooks/useMarkdownEditorView";
import { applyMarkdownFormat, type MarkdownFormat } from "../utils/markdownEdit";
import type { VisualBlocker } from "../utils/visualMarkdown";
import { ActiveFieldFrame, ActiveFieldToolbar } from "./ActiveFieldFrame";
import { AutoGrowTextarea } from "./AutoGrowTextarea";
import { MarkdownView } from "./MarkdownView";
import { Tabs, tabPanelProps } from "./Tabs";
import { ToolbarButton } from "./ToolbarButton";

// The visual editor (and TipTap with it) is downloaded when a Visual view is first shown, not with every form.
const VisualMarkdownEditor = lazy(() => import("./VisualMarkdownEditor").then((module) => ({ default: module.VisualMarkdownEditor })));

type View = "visual" | "write" | "preview";

/**
 * The Write view's formatting buttons. Memoised: a form with many Markdown fields re-renders every one of them on each
 * keystroke in any field, and ten buttons with tooltips per field made typing visibly slower.
 */
const WriteToolbar = memo(function WriteToolbar({ onFormat, disabled }: { onFormat: (format: MarkdownFormat) => void; disabled?: boolean }) {
  const text = useStrings().markdown;
  const button = (format: MarkdownFormat, icon: typeof Bold, label: string) => (
    <ToolbarButton icon={icon} label={label} disabled={disabled} onClick={() => onFormat(format)} />
  );
  return (
    <div className="row" role="toolbar" aria-label={text.toolbar} style={{ flexWrap: "wrap", gap: "var(--space-1)" }}>
      {button("bold", Bold, text.bold)}
      {button("italic", Italic, text.italic)}
      {button("heading", Heading2, text.heading)}
      {button("bulleted", List, text.bulleted)}
      {button("numbered", ListOrdered, text.numbered)}
      {button("quote", Quote, text.quote)}
      {button("code", Code, text.code)}
      {button("link", Link2, text.link)}
      {button("table", Table, text.table)}
      {button("diagram", Workflow, text.diagram)}
    </div>
  );
});

type TextAreaExtras = Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "value" | "onChange" | "rows" | "className" | "style">;

/**
 * @param value The Markdown source.
 * @param onChange Called with the new source after every edit.
 * @param rows Minimum visible lines of the Write view.
 * @param ariaLabel The text area's accessible name.
 * @param disabled Whether editing is unavailable.
 * @param textareaProps Further attributes for the text area (id, maxLength, required).
 * @param simple Offer Write and Preview only, with no visual view.
 * @param math The text holds equations (`\( x \)`, `$$ x $$`): Write and Preview only, and Preview draws them.
 * @param toolbar Whether the Write view shows the formatting buttons (default true); a narrow pop-over leaves them out.
 */
export function MarkdownEditor({ value, onChange, rows = 4, ariaLabel, disabled, textareaProps, simple, math, toolbar = true }: {
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  ariaLabel: string;
  disabled?: boolean;
  textareaProps?: TextAreaExtras;
  simple?: boolean;
  math?: boolean;
  toolbar?: boolean;
}) {
  const sourceOnly = Boolean(simple || math);
  const strings = useStrings();
  const text = strings.markdown;
  const idPrefix = useId();
  const [preferred, remember] = useMarkdownEditorView();
  // Set when the text cannot be edited visually: the field falls back to Write and says why.
  const [blocker, setBlocker] = useState<VisualBlocker | null>(null);
  const [chosen, setChosen] = useState<View | null>(null);
  const view: View = chosen ?? (sourceOnly && preferred === "visual" ? "write" : preferred);
  const area = useRef<HTMLTextAreaElement>(null);
  const onBlocked = useCallback((reason: VisualBlocker) => {
    setBlocker(reason);
    setChosen("write");
  }, []);

  function choose(next: View) {
    setChosen(next);
    if (next !== "preview" && !sourceOnly) remember(next);
    // A new attempt at the Visual view re-checks the current text.
    if (next === "visual") setBlocker(null);
  }

  // The toolbar's handler is stable, so it reads the current value and callback through a ref.
  const latest = useRef({ value, onChange });
  useEffect(() => {
    latest.current = { value, onChange };
  });
  const apply = useCallback((format: MarkdownFormat) => {
    const el = area.current;
    if (!el) return;
    const result = applyMarkdownFormat(latest.current.value, el.selectionStart, el.selectionEnd, format);
    latest.current.onChange(result.value);
    // The value is applied on the next render; the selection is restored once it has.
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(result.selectionStart, result.selectionEnd);
    });
  }, []);

  return (
    <ActiveFieldFrame className="markdown-editor stack" style={{ gap: "var(--space-1)" }}>
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: "var(--space-1)" }}>
        <Tabs
          idPrefix={idPrefix} active={view} onChange={choose}
          tabs={[
            ...(sourceOnly ? [] : [{ key: "visual" as const, label: text.visual }]),
            { key: "write" as const, label: text.write }, { key: "preview" as const, label: text.preview },
          ]}
        />
        {view === "write" && toolbar && <ActiveFieldToolbar><WriteToolbar onFormat={apply} disabled={disabled} /></ActiveFieldToolbar>}
      </div>
      {blocker && view === "write" && (
        <p className="text-muted" role="status">
          {blocker === "mathematics" ? strings.richText.visualUnavailableMathematics : strings.richText.visualUnavailableFormat}
        </p>
      )}
      {view === "visual" ? (
        <div {...tabPanelProps(idPrefix, "visual")}>
          <Suspense fallback={<p className="text-muted" role="status">{text.visualLoading}</p>}>
            <VisualMarkdownEditor
              value={value} onChange={onChange} onBlocked={onBlocked} rows={rows} ariaLabel={ariaLabel} disabled={disabled}
              textareaProps={textareaProps}
            />
          </Suspense>
        </div>
      ) : view === "write" ? (
        <div {...tabPanelProps(idPrefix, "write")}>
          <AutoGrowTextarea
            {...textareaProps} textareaRef={area} rows={rows} value={value} onChange={onChange} aria-label={ariaLabel} disabled={disabled}
          />
        </div>
      ) : (
        <div {...tabPanelProps(idPrefix, "preview")} className="markdown-preview card">
          {value.trim() === "" ? <p className="text-muted">{text.previewEmpty}</p> : <MarkdownView text={value} math={math} />}
        </div>
      )}
    </ActiveFieldFrame>
  );
}
