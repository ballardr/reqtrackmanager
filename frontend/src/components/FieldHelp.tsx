/**
 * Module: components/FieldHelp
 *
 * The help affordance every non-obvious form field carries (docs/ux-style-guide.md, "Pattern: field
 * help"): a `(?)` button after the field's caption that reveals one or two sentences saying what the
 * field is, what it affects and typical values. `FieldCaption` is the caption line every shared field
 * component renders, so the label and the help sit the same way everywhere.
 *
 * Design decisions:
 * - The text opens in place under the caption (a disclosure), not in a floating `Popover`: fields are
 *   built inside dialogs and popovers, and a popover opened from a popover is not allowed. An inline
 *   disclosure also needs no positioning, and a tap works the same as a click.
 * - The button is a keyboard-focusable control named "Help: {label}"; Escape closes the text while focus
 *   is on the button or inside the text. It is named by visually-hidden text, not `aria-label`, so a
 *   label lookup for the field ("Name") finds the field alone and never also its help button.
 * - A field that is self-explanatory (a title, a name) passes `helpNotNeeded` instead of `help`, which
 *   keeps the opt-out greppable; `scripts/check_field_help.py` fails on a field with neither.
 * - A button inside a `<label>` becomes that label's control (the first labelable descendant), so a
 *   field with help never wraps its control in the label: `FieldShell` ties a sibling `<label>` to the
 *   control by `htmlFor` instead, and keeps the plain wrapping `<label>` for a field without help.
 */
import { CircleHelp } from "lucide-react";
import { useId, useState } from "react";
import type { ReactNode } from "react";

import { useStrings } from "../context/TerminologyContext";

/** The props every shared field component takes for field help: give `help`, or `helpNotNeeded` when the field explains itself. */
export type FieldHelpProps = {
  /** One or two sentences (from `strings.help`) saying what the field is, what it affects and typical values. */
  help?: string;
  /** Opt-out for a self-explanatory field (a title, a name); never combine with `help`. */
  helpNotNeeded?: boolean;
  /**
   * Marks the field required: a `*` after the caption and `required` on the control. Mark exactly the fields the
   * form blocks on and the API rejects; an unmarked field is optional and its label never says so
   * (docs/ux-style-guide.md, "Pattern: required fields").
   */
  required?: boolean;
};

/**
 * The `*` after a required field's caption. The star is drawn by CSS (`.field-required::after`), so it is
 * not part of the caption's text (a label lookup by its text still finds the field) and assistive
 * technology never reads it: the control itself carries `required`.
 */
export function RequiredMark() {
  return <span className="field-required" aria-hidden="true" />;
}

/**
 * The `(?)` button and the text it reveals.
 *
 * @param label The field's visible caption; names the button ("Help: {label}").
 * @param help The help text.
 */
export function FieldHelp({ label, help }: { label: string; help: string }) {
  const strings = useStrings();
  const [open, setOpen] = useState(false);
  const textId = useId();

  return (
    <>
      <button
        type="button"
        className="field-help__button"
        aria-expanded={open}
        aria-controls={open ? textId : undefined}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === "Escape" && open) {
            e.stopPropagation();
            setOpen(false);
          }
        }}
      >
        <CircleHelp aria-hidden="true" />
        <span className="sr-only">{strings.common.fieldHelp(label)}</span>
      </button>
      {open && (
        <span id={textId} role="note" className="field-help__text">
          {help}
        </span>
      )}
    </>
  );
}

/**
 * A field's caption line: the label text, then the help button when the field has `help`, then an
 * optional control of the caller's (an `OverridePill`).
 *
 * @param label The visible caption.
 * @param help The help text, when the field has any.
 * @param extra A control beside the caption.
 * @param muted Renders the small bold style detail pages use for a field group's caption.
 * @param required Adds the `*` after the caption.
 */
export function FieldCaption({
  label, help, extra, htmlFor, muted, required,
}: { label: string; help?: string; extra?: ReactNode; htmlFor?: string; muted?: boolean; required?: boolean }) {
  const mark = required ? <RequiredMark /> : null;
  const text = htmlFor ? <label htmlFor={htmlFor}>{label}{mark}</label> : <span>{label}{mark}</span>;
  const mutedText = <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>{label}{mark}</span>;
  if (!help && !extra) return muted ? mutedText : text;
  return (
    <span className="field-caption">
      {muted ? mutedText : text}
      {extra}
      {help && <FieldHelp label={label} help={help} />}
    </span>
  );
}

/**
 * The labelled block every single-control field is built on: the caption over the control, and an
 * optional hint under it.
 *
 * Without help or `extra` the whole block is one `<label>`, so clicking the caption focuses the control.
 * With either, the caption is a sibling `<label htmlFor>` (a button or pill inside the label would
 * hijack it) and the control carries `controlId`.
 *
 * @param label The visible caption.
 * @param controlId The control's `id`, always set on it so the caption can point at it.
 * @param help The help text, when the field has any.
 * @param extra A control beside the caption (an `OverridePill`).
 * @param hint Muted text under the control.
 * @param required Adds the `*` after the caption (the control carries `required` itself).
 * @param children The control.
 */
export function FieldShell({
  label, controlId, help, extra, hint, required, children,
}: { label: string; controlId: string; help?: string; extra?: ReactNode; hint?: ReactNode; required?: boolean; children: ReactNode }) {
  const hintNode = hint && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{hint}</span>;
  if (!help && !extra) {
    return (
      <label className="stack" style={{ gap: "var(--space-1)" }}>
        <span>{label}{required && <RequiredMark />}</span>
        {children}
        {hintNode}
      </label>
    );
  }
  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      <FieldCaption htmlFor={controlId} label={label} extra={extra} help={help} required={required} />
      {children}
      {hintNode}
    </div>
  );
}
