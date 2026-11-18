/**
 * Module: modules/architecture/NoteModeToggle
 *
 * The toolbar switch for the block diagram editor's note mode, beside Comment: with it on, a click on empty canvas places a
 * note there. It is the shared `CanvasModeToggle` with the note wording, so it is the same height and look as Comment.
 */
import { CanvasModeToggle } from "../../components/CanvasModeToggle";

/** The switch's label, also its accessible name. */
export const NOTE_MODE_LABEL = "Note";

/** One line per state, shown as the button's tooltip (the project's rule for help on a button). */
export const NOTE_MODE_HELP =
  "On: a click on empty canvas places a note there, ready for its text; the mode stays on so several notes can be placed, until it is switched off or Escape is pressed.\nOff: a click selects and edits the drawing again.";

/**
 * @param on Whether note mode is on.
 * @param onChange Called with the new state when the button is pressed.
 * @param disabled Disables the switch (an archived diagram cannot take notes).
 */
export function NoteModeToggle({ on, onChange, disabled }: { on: boolean; onChange: (next: boolean) => void; disabled?: boolean }) {
  return <CanvasModeToggle label={NOTE_MODE_LABEL} help={NOTE_MODE_HELP} on={on} onChange={onChange} disabled={disabled} />;
}
