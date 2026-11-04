/**
 * Module: components/MarkButtons
 *
 * The Bold and Italic buttons beside a text input that reads `**bold**` and `*italic*` marks: a header or footer cell, a
 * heading's words, a text block. A press wraps the input's selected words in the mark (see `useTextSelections`); nothing
 * is stored apart from the text itself.
 *
 * Design decisions: the buttons are the shared `ToggleButton` in its action form (no pressed state), because the
 * mark lives in the text, not in a field, and the same words can be bold in one place and plain in another. The caller
 * names each button, so a row of cells says which cell it acts on.
 */
import { useStrings } from "../context/TerminologyContext";
import { ToggleButton } from "./ToggleButton";

/**
 * @param nameOf Gives the accessible name of a button from its label ("Bold", "Italic").
 * @param onMark Called with `**` (bold) or `*` (italic).
 * @param disabled Disables both buttons.
 */
export function MarkButtons({
  nameOf, onMark, disabled,
}: {
  nameOf: (mark: string) => string;
  onMark: (marker: string) => void;
  disabled?: boolean;
}) {
  const text = useStrings().pageSetup.band;
  return (
    <>
      <ToggleButton label={nameOf(text.boldButton)} iconOnly={false} disabled={disabled} onClick={() => onMark("**")}>
        <strong>B</strong>
      </ToggleButton>
      <ToggleButton label={nameOf(text.italicButton)} iconOnly={false} disabled={disabled} onClick={() => onMark("*")}>
        <em>I</em>
      </ToggleButton>
    </>
  );
}
