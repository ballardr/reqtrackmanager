/**
 * Module: components/CommentModeToggle
 *
 * The toolbar switch that turns a graph canvas's comment mode on and off, shared by every editor that comments on a
 * canvas so the label, the pressed look and the help are one thing (`useCanvasComments` supplies the state).
 *
 * Design decisions: the help is the button's own tooltip (one line per state), never a `(?)` beside it
 * (docs/ux-style-guide.md, "Pattern: help on interactive elements"); the button is a small `ToggleButton`, matching its
 * toolbar neighbours' height.
 */
import { useStrings } from "../context/TerminologyContext";
import { ToggleButton } from "./ToggleButton";

/**
 * @param on Whether comment mode is on.
 * @param onChange Called with the new state when the button is pressed.
 */
export function CommentModeToggle({ on, onChange }: { on: boolean; onChange: (next: boolean) => void }) {
  const text = useStrings().canvasComments;
  return (
    <ToggleButton label={text.modeLabel} iconOnly={false} pressed={on} help={text.modeHelp} onClick={() => onChange(!on)}>
      {text.modeLabel}
    </ToggleButton>
  );
}
