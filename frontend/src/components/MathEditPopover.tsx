/**
 * Module: components/MathEditPopover
 *
 * The small panel in which an equation is written or changed, with the equation drawn beneath the TeX as it is typed,
 * and the toolbar button that opens it.
 *
 * Responsibilities:
 * - `MathEditPopover`: take the TeX, show the equation as the screen and the reports will draw it, say why it cannot
 *   be drawn (the allow-list `utils/mathTex.texProblem`, an empty equation, a closing delimiter inside it), and hand
 *   the TeX back on Insert (or Apply, for an equation being changed).
 * - `MathToolbarButton`: the Inline equation and Equation block buttons of every editor toolbar; each opens the
 *   panel, prefilled with the text selected in the field, and reports the TeX to the editor that owns the field.
 *
 * Design decisions:
 * - One panel serves the Write view, the Visual view and a change to an equation already in the Visual view, so the
 *   three behave alike; the editor decides what the TeX becomes (source text or an equation node).
 * - The preview draws only what `utils/mathTex.texProblem` allows, the same rule the report engine applies, so a
 *   formula that would be refused in a report is not shown as fine here.
 * - KaTeX is loaded when a preview is first drawn, not with the editor.
 *
 * Dependencies: `Popover`, `ToolbarButton`, `TextField`, `MathEquation` (loaded on first use), `utils/mathTex`,
 * `utils/visualMathNode`.
 */
import { Radical, Sigma } from "lucide-react";
import { lazy, Suspense, useEffect, useRef, useState, type FormEvent, type RefObject } from "react";

import { useStrings } from "../context/TerminologyContext";
import { texProblem } from "../utils/mathTex";
import { mathProblem } from "../utils/visualMathNode";
import { TextField } from "./FormFields";
import { Popover } from "./Popover";
import { ToolbarButton } from "./ToolbarButton";

const MathEquation = lazy(() => import("./MathEquation").then((module) => ({ default: module.MathEquation })));

/**
 * @param anchorRef The button the panel opens from.
 * @param display Whether the equation is a display equation (its own line) rather than inline.
 * @param initialTex The TeX to start from (the selected text, or the equation being changed).
 * @param changing Whether an existing equation is being changed (the action reads Apply, not Insert).
 * @param onApply Called with the TeX when the person confirms.
 * @param onClose Called when the panel is dismissed.
 */
export function MathEditPopover({ anchorRef, display, initialTex, changing, onApply, onClose }: {
  anchorRef: RefObject<HTMLElement | null>;
  display: boolean;
  initialTex: string;
  changing?: boolean;
  onApply: (tex: string) => void;
  onClose: () => void;
}) {
  const text = useStrings().richText;
  const strings = useStrings();
  const [tex, setTex] = useState(initialTex.trim().replace(/\s*\n\s*/g, " "));
  const entered = tex.trim() !== "";
  const delimiter = mathProblem(tex, display);
  const unsupported = entered ? texProblem(tex) : null;
  const blocked = delimiter !== null || unsupported !== null;
  const form = useRef<HTMLFormElement>(null);
  // Focus the TeX field once the panel is placed: the panel is hidden until it is measured, and a hidden field cannot
  // take focus, so `autoFocus` alone leaves focus on the field's help button (the first control in the panel).
  useEffect(() => { form.current?.querySelector("input")?.focus(); }, []);

  function submit(event: FormEvent) {
    event.preventDefault();
    event.stopPropagation(); // a form inside an editor field's form must not submit the record
    if (!blocked) onApply(tex.trim());
  }

  return (
    <Popover anchorRef={anchorRef} onClose={onClose} title={display ? text.mathBlockTitle : text.mathInlineTitle} fit>
      <form ref={form} className="stack math-edit" onSubmit={submit} style={{ gap: "var(--space-2)", minWidth: "min(24rem, 80vw)" }}>
        <TextField
          label={text.mathSource} value={tex} onChange={setTex} help={strings.help.mathTex} placeholder="x^2 + y^2 = z^2"
          inputProps={{ spellCheck: false, autoComplete: "off" }}
        />
        <div className="stack" style={{ gap: "var(--space-1)" }}>
          <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>{text.mathPreview}</span>
          <div className="math-edit__preview card" role="img" aria-label={text.mathPreview} data-testid="math-preview">
            {entered && !blocked ? (
              <Suspense fallback={<span className="text-muted">{tex}</span>}><MathEquation tex={tex} display={display} /></Suspense>
            ) : (
              <span className="text-muted">{text.mathPreviewEmpty}</span>
            )}
          </div>
          {entered && delimiter === "delimiter" && <span role="alert" style={{ color: "var(--color-danger)" }}>{display ? text.mathDelimiterBlock : text.mathDelimiterInline}</span>}
          {entered && delimiter === "blank-line" && <span role="alert" style={{ color: "var(--color-danger)" }}>{text.mathBlankLine}</span>}
          {entered && delimiter === null && unsupported !== null && <span role="alert" style={{ color: "var(--color-danger)" }}>{unsupported}</span>}
        </div>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn btn-sm" onClick={onClose}>{strings.common.cancel}</button>
          <button type="submit" className="btn btn-sm btn-primary" disabled={!entered || blocked}>
            {changing ? text.mathApply : text.mathInsert}
          </button>
        </div>
      </form>
    </Popover>
  );
}

/**
 * A toolbar button that opens the equation panel.
 *
 * @param display True for the Equation block button, false for Inline equation.
 * @param readSelection Reads the text selected in the field when the panel opens (it starts the equation).
 * @param onApply Called with the TeX when the person confirms; the editor puts the equation in the field.
 * @param disabled Whether editing is unavailable.
 */
export function MathToolbarButton({ display, readSelection, onApply, disabled }: {
  display: boolean;
  readSelection: () => string;
  onApply: (tex: string, display: boolean) => void;
  disabled?: boolean;
}) {
  const text = useStrings().richText;
  const anchor = useRef<HTMLButtonElement>(null);
  const [initial, setInitial] = useState<string | null>(null);
  const open = initial !== null;
  return (
    <>
      <ToolbarButton
        icon={display ? Sigma : Radical} label={display ? text.mathBlock : text.mathInline} disabled={disabled} buttonRef={anchor} opens={open}
        onClick={() => setInitial(open ? null : readSelection())}
      />
      {open && (
        <MathEditPopover
          anchorRef={anchor} display={display} initialTex={initial} onClose={() => setInitial(null)}
          onApply={(tex) => { setInitial(null); onApply(tex, display); }}
        />
      )}
    </>
  );
}
