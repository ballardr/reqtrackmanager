/**
 * Module: components/MarkdownEditor
 *
 * The editing control for a Markdown field: a Visual view (`VisualMarkdownEditor`), a Write view (the source,
 * with a formatting toolbar) and a Preview view (the rendering readers see, including diagrams). It owns no
 * value; the caller holds the text, which is always the Markdown source.
 *
 * - The toolbar and the view switch (`ViewSwitch`, three icon buttons at the end of the caption line,
 *   `renderCaption`) show only while the field is in use (`ActiveFieldFrame`) but keep their place, so no view
 *   moves the field. Without a caption (a comment box) the switch ends the toolbar row.
 * - All views share one box (`.md-box`): an empty field is `rows` lines (default 2) in every view and grows with
 *   its text (`AutoGrowTextarea` for Write). The textarea keeps the field's accessible name and id.
 * - A new field opens in the person's remembered view (Visual unless they chose Write); only a view the person
 *   chooses is remembered. It falls back to Write, with a stated reason, when the text cannot be edited visually
 *   without changing it. The visual editor is lazy-loaded so a form that never shows it does not download TipTap.
 * - `simple` offers Write and Preview only. `math` draws equations (`\( x \)`, `$$ x $$`) in Visual and Preview and
 *   adds Inline equation and Equation block buttons with a live TeX preview.
 * - A Picture button (`PictureToolbarButton`) appears wherever the field sits inside a record page that supplies
 *   pictures (`MarkdownImageSourceProvider`) and is not `simple`; it writes `![alt](attachment:<file id>)`.
 */
import { Bold, Code, Eye, FileCode, Heading2, Italic, Link2, List, ListOrdered, Quote, Table, Type, Workflow } from "lucide-react";
import { lazy, memo, Suspense, useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode, type TextareaHTMLAttributes } from "react";

import { useStrings } from "../context/TerminologyContext";
import { useMarkdownEditorView } from "../hooks/useMarkdownEditorView";
import { applyMarkdownFormat, insertMarkdownMath, insertMarkdownPicture, type MarkdownFormat } from "../utils/markdownEdit";
import type { VisualBlocker } from "../utils/visualMarkdown";
import { ActiveFieldFrame, ActiveFieldToolbar } from "./ActiveFieldFrame";
import { AutoGrowTextarea } from "./AutoGrowTextarea";
import { MarkdownView } from "./MarkdownView";
import { MathToolbarButton } from "./MathEditPopover";
import { PictureToolbarButton, type PictureChoice } from "./PicturePicker";
import { ToolbarButton } from "./ToolbarButton";
import { ViewSwitch, type ViewSwitchOption } from "./ViewSwitch";

// The visual editor (and TipTap with it) is downloaded when a Visual view is first shown, not with every form.
const VisualMarkdownEditor = lazy(() => import("./VisualMarkdownEditor").then((module) => ({ default: module.VisualMarkdownEditor })));

type View = "visual" | "write" | "preview";

/** The minimum height of a view's box, in lines of its text (read by `.md-box`). */
function boxStyle(rows: number): CSSProperties {
  return { "--md-rows": rows } as CSSProperties;
}

/**
 * The Write view's formatting buttons. Memoised: a form with many Markdown fields re-renders every one on each
 * keystroke, and ten buttons with tooltips per field made typing visibly slower.
 */
const WriteToolbar = memo(function WriteToolbar({ onFormat, onMath, onPicture, readSelection, disabled }: {
  onFormat: (format: MarkdownFormat) => void;
  /** Present for a field that may hold pictures: puts the chosen picture in the text. */
  onPicture?: (choice: PictureChoice) => void;
  /** Present for a field that holds equations: puts an equation of the given TeX in the text. */
  onMath?: (tex: string, display: boolean) => void;
  readSelection: () => string;
  disabled?: boolean;
}) {
  const text = useStrings().markdown;
  const button = (format: MarkdownFormat, icon: typeof Bold, label: string) => (
    <ToolbarButton icon={icon} label={label} disabled={disabled} onClick={() => onFormat(format)} />
  );
  const separator = <span className="toolbar-divider" role="separator" aria-orientation="vertical" />;
  return (
    <div className="row editor-toolbar" role="toolbar" aria-label={text.toolbar} style={{ flexWrap: "wrap", gap: "var(--space-1)", alignItems: "center" }}>
      {button("bold", Bold, text.bold)}
      {button("italic", Italic, text.italic)}
      {button("heading", Heading2, text.heading)}
      {separator}
      {button("bulleted", List, text.bulleted)}
      {button("numbered", ListOrdered, text.numbered)}
      {button("quote", Quote, text.quote)}
      {button("code", Code, text.code)}
      {separator}
      {button("link", Link2, text.link)}
      {button("table", Table, text.table)}
      {button("diagram", Workflow, text.diagram)}
      {onPicture && <PictureToolbarButton onInsert={onPicture} disabled={disabled} />}
      {onMath && (
        <>
          <MathToolbarButton display={false} readSelection={readSelection} onApply={onMath} disabled={disabled} />
          <MathToolbarButton display readSelection={readSelection} onApply={onMath} disabled={disabled} />
        </>
      )}
    </div>
  );
});

type TextAreaExtras = Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "value" | "onChange" | "rows" | "className" | "style">;

/**
 * @param value The Markdown source.
 * @param onChange Called with the new source after every edit.
 * @param rows Minimum visible lines of every view (default 2, the smallest box that holds a placeholder and a caret with room); each view grows past it.
 * @param ariaLabel The text area's accessible name.
 * @param disabled Whether editing is unavailable.
 * @param textareaProps Further attributes for the text area (id, maxLength, required).
 * @param simple Offer Write and Preview only, with no visual view.
 * @param math The text holds equations (`\( x \)`, `$$ x $$`): the views draw them and the toolbars offer the equation buttons.
 * @param toolbar Whether the Write view shows the formatting buttons (default true); a narrow pop-over leaves them out.
 * @param renderCaption Draws the field's caption line, given the view switch to put at its end (`FieldCaption` `actions`);
 * without it the switch ends the toolbar row.
 */
export function MarkdownEditor({ value, onChange, rows = 2, ariaLabel, disabled, textareaProps, simple, math, toolbar = true, renderCaption }: {
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  ariaLabel: string;
  disabled?: boolean;
  textareaProps?: TextAreaExtras;
  simple?: boolean;
  math?: boolean;
  toolbar?: boolean;
  renderCaption?: (viewSwitch: ReactNode) => ReactNode;
}) {
  const sourceOnly = Boolean(simple);
  const strings = useStrings();
  const text = strings.markdown;
  const [preferred, remember] = useMarkdownEditorView();
  // Set when the text cannot be edited visually: the field falls back to Write and says why.
  const [blocker, setBlocker] = useState<VisualBlocker | null>(null);
  const [chosen, setChosen] = useState<View | null>(null);
  // The remembered view is the starting view of a field when it is first drawn; choosing a view changes this field only,
  // so working in one field never reshapes the others on the form.
  const [startView] = useState(preferred);
  const view: View = chosen ?? (sourceOnly && startView === "visual" ? "write" : startView);
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
  const applyMath = useCallback((tex: string, display: boolean) => {
    const el = area.current;
    if (!el) return;
    const result = insertMarkdownMath(latest.current.value, el.selectionStart, el.selectionEnd, tex, display);
    latest.current.onChange(result.value);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(result.selectionStart, result.selectionEnd);
    });
  }, []);
  const applyPicture = useCallback((choice: PictureChoice) => {
    const el = area.current;
    if (!el) return;
    const result = insertMarkdownPicture(latest.current.value, el.selectionStart, el.selectionEnd, choice);
    latest.current.onChange(result.value);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(result.selectionStart, result.selectionEnd);
    });
  }, []);
  const readSelection = useCallback(() => {
    const el = area.current;
    return el ? latest.current.value.slice(el.selectionStart, el.selectionEnd) : "";
  }, []);

  const options: ViewSwitchOption<View>[] = [
    ...(sourceOnly ? [] : [{ key: "visual" as const, label: text.visual, icon: Type }]),
    { key: "write" as const, label: text.write, icon: FileCode },
    { key: "preview" as const, label: text.preview, icon: Eye },
  ];
  const viewSwitch = <ViewSwitch label={text.editorView} options={options} active={view} onChange={choose} disabled={disabled} />;
  // A field with a caption line carries the switch there; one without ends its toolbar row with it. The switch keeps
  // its place in that row whichever view shows (Visual draws the row inside its own toolbar), so pressing it never
  // replaces the element that has the focus.
  const trailing = renderCaption ? undefined : viewSwitch;
  const writeToolbar = view === "write" && toolbar;
  const writeButtons = (
    <WriteToolbar
      onFormat={apply} onMath={math ? applyMath : undefined} onPicture={sourceOnly ? undefined : applyPicture}
      readSelection={readSelection} disabled={disabled}
    />
  );
  const style = boxStyle(rows);

  return (
    <ActiveFieldFrame className="markdown-editor stack" style={{ gap: "var(--space-1)" }}>
      {renderCaption?.(<ActiveFieldToolbar reserveSpace>{viewSwitch}</ActiveFieldToolbar>)}
      {renderCaption ? (
        writeToolbar && <ActiveFieldToolbar>{writeButtons}</ActiveFieldToolbar>
      ) : view !== "visual" && (
        <ActiveFieldToolbar>
          <div className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap", alignItems: "flex-start" }}>
            {writeToolbar ? writeButtons : <span />}
            {trailing}
          </div>
        </ActiveFieldToolbar>
      )}
      {blocker && view === "write" && (
        <p className="text-muted" role="status">
          {blocker === "mathematics" ? strings.richText.visualUnavailableMathematics : strings.richText.visualUnavailableFormat}
        </p>
      )}
      {view === "visual" ? (
        <Suspense fallback={<p className="text-muted" role="status">{text.visualLoading}</p>}>
          <VisualMarkdownEditor
            value={value} onChange={onChange} onBlocked={onBlocked} rows={rows} ariaLabel={ariaLabel} disabled={disabled}
            textareaProps={textareaProps} math={math} toolbarTrailing={trailing}
          />
        </Suspense>
      ) : view === "write" ? (
        <AutoGrowTextarea
          {...textareaProps} className="input md-box" style={style} textareaRef={area} rows={rows} value={value} onChange={onChange}
          aria-label={ariaLabel} disabled={disabled}
        />
      ) : (
        <div role="region" aria-label={text.preview} tabIndex={0} className="md-box markdown-preview" style={style}>
          {value.trim() === "" ? <p className="text-muted">{text.previewEmpty}</p> : <MarkdownView text={value} math={math} />}
        </div>
      )}
    </ActiveFieldFrame>
  );
}
