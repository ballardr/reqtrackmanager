/**
 * Module: components/ColourChoiceField
 *
 * The one control for choosing a colour in a report layout: a button showing the current colour (a swatch and its name, never
 * colour alone) that opens a popover with the branding colour first, then the layout's own scheme, the organisation's, the
 * standard four, white, black and (where the field allows it) no colour, then a custom colour.
 *
 * Responsibilities:
 * - Report a colour word: a hex colour, a reserved word (`accent`, `white` ...) or a scheme name. A name is kept as a name,
 *   so a change to the scheme changes everything that uses it.
 * - Show each choice's actual colour, resolved the way the server resolves it (`utils/reportColours`).
 * - `ColourChoiceList` is the list on its own, for a place that already is a popover (a scheme entry's settings), so popovers
 *   never nest.
 *
 * Design decisions: one control for every colour setting (the shape block's fill and outline, a scheme entry's colour, and the
 * custom-table cell colours later), instead of a hex box copied per form. A custom colour reuses `HexColourInput`, the pair
 * `ColorField` is built on. Changes apply as they are made, so choosing a line closes the popover.
 */
import { useId, useRef, useState } from "react";

import { useStrings } from "../context/TerminologyContext";
import { normaliseHexColour } from "../utils/color";
import { colourChoices, colourWordLabel, resolveColourWord, type ColourContext, type ColourEntry } from "../utils/reportColours";
import { FieldShell, type FieldHelpProps } from "./FieldHelp";
import { HexColourInput } from "./HexColourInput";
import { Popover } from "./Popover";

/** A small round chip of a colour; a missing colour (none) is drawn struck through. */
export function ColourSwatch({ hex }: { hex: string | null }) {
  return <span className={`colour-chip${hex === null ? " colour-chip--none" : ""}`} style={hex ? { background: hex } : undefined} aria-hidden="true" />;
}

/**
 * The list of colour choices (branding colour, the layout's scheme, the organisation's, standard four, white, black, none, and a
 * custom colour), without a button or popover around it.
 *
 * @param value The stored colour word; `""` when not set.
 * @param onChoose Called with the chosen word (`""` for the unset line); `custom` is true for a hex typed or picked, which is
 *   reported as it changes, so a caller keeps the list open.
 * @param name What the colour is for (the field's caption), naming the custom controls.
 * @param emptyLabel When given, the list starts with a line that clears the field and says what unset means.
 * @param allowNone Whether "No colour" (`none`) is a choice.
 * @param allowNames Whether scheme names are choices (a scheme entry's own colour points at a colour, never at a name).
 */
export function ColourChoiceList({
  value, onChoose, name, context, layoutPalette = [], emptyLabel, allowNone = true, allowNames = true,
}: {
  value: string;
  onChoose: (word: string, custom?: boolean) => void;
  name: string;
  context: ColourContext;
  layoutPalette?: ColourEntry[];
  emptyLabel?: string;
  allowNone?: boolean;
  allowNames?: boolean;
}) {
  const text = useStrings().reportColours;
  const choices = colourChoices(context, layoutPalette, {
    accent: text.wordLabels.accent, light: text.wordLabels.accent_light, dark: text.wordLabels.accent_dark,
    white: text.wordLabels.white, black: text.wordLabels.black, none: text.wordLabels.none,
  }, { allowNone, allowNames });
  const hex = (word: string) => resolveColourWord(word, context, layoutPalette);
  const isHex = value !== "" && normaliseHexColour(value) !== null;
  const groups = ["branding", "scheme", "organisation", "standard", "fixed"] as const;
  return (
    <div className="stack" style={{ gap: "var(--space-2)" }}>
      {emptyLabel && (
        <button type="button" className="colour-choice__line" aria-pressed={value === ""} onClick={() => onChoose("")}>
          <ColourSwatch hex={null} /><span>{emptyLabel}</span>
        </button>
      )}
      {groups.map((group) => {
        const lines = choices.filter((c) => c.group === group);
        if (lines.length === 0) return null;
        return (
          <div key={group} role="group" aria-label={text.groupHeadings[group]} className="stack" style={{ gap: 2 }}>
            <span className="text-muted colour-choice__heading">{text.groupHeadings[group]}</span>
            {lines.map((c) => (
              <button key={c.word} type="button" className="colour-choice__line" aria-pressed={value === c.word} onClick={() => onChoose(c.word)}>
                <ColourSwatch hex={hex(c.word)} />
                <span>{c.label}</span>
                {hex(c.word) && <span className="text-muted">{hex(c.word)}</span>}
              </button>
            ))}
          </div>
        );
      })}
      <div role="group" aria-label={text.customHeading} className="stack" style={{ gap: 2 }}>
        <span className="text-muted colour-choice__heading">{text.custom}</span>
        <HexColourInput value={isHex ? value : hex(value) ?? "#000000"} onChange={(next) => onChoose(next, true)} name={`${name} (${text.customHeading})`} />
      </div>
    </div>
  );
}

/**
 * @param label The field's caption.
 * @param value The stored colour word; `""` when the field is not set.
 * @param onChange Called with the new word, or `""` to clear the field.
 * @param context The branding colour and the organisation's scheme.
 * @param layoutPalette The layout's own scheme.
 * @param emptyLabel What an unset field means ("No outline", "Default (branding colour)"); when given, the list starts with a
 *   line that clears the field.
 * @param allowNone Whether "No colour" (`none`) is a choice.
 * @param allowNames Whether scheme names are choices.
 * @param disabled Read-only.
 * @param hint Muted text under the control.
 */
export function ColourChoiceField({
  label, value, onChange, context, layoutPalette = [], emptyLabel, allowNone = true, allowNames = true, disabled = false, hint,
  help, required,
}: FieldHelpProps & {
  label: string;
  value: string;
  onChange: (word: string) => void;
  context: ColourContext;
  layoutPalette?: ColourEntry[];
  emptyLabel?: string;
  allowNone?: boolean;
  allowNames?: boolean;
  disabled?: boolean;
  hint?: string;
}) {
  const text = useStrings().reportColours;
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const isHex = value !== "" && normaliseHexColour(value) !== null;
  const unset = value === "";
  const shownName = unset ? (emptyLabel ?? text.noColour) : isHex ? normaliseHexColour(value) ?? value : colourWordLabel(value, text.wordLabels);
  const shownHex = unset ? null : resolveColourWord(value, context, layoutPalette);
  return (
    <FieldShell label={label} controlId={id} help={help} hint={hint} required={required}>
      <button
        ref={trigger} id={id} type="button" className="btn colour-choice" disabled={disabled} aria-haspopup="dialog" aria-expanded={open}
        aria-label={text.buttonName(label, shownName)} onClick={() => setOpen((o) => !o)}
      >
        <ColourSwatch hex={shownHex} />
        <span>{shownName}</span>
        {shownHex && !isHex && <span className="text-muted">{shownHex}</span>}
      </button>
      {open && (
        <Popover anchorRef={trigger} title={text.popoverTitle(label)} onClose={() => setOpen(false)} fit>
          <ColourChoiceList
            value={value} name={label} context={context} layoutPalette={layoutPalette} emptyLabel={emptyLabel} allowNone={allowNone}
            allowNames={allowNames} onChoose={(word, custom) => { onChange(word); if (!custom) setOpen(false); }}
          />
        </Popover>
      )}
    </FieldShell>
  );
}
