/**
 * Module: components/CommentModeToggle
 *
 * The toolbar switch that turns a graph canvas's comment mode on and off, shared by every editor that comments on a
 * canvas so the label, the pressed look and the help are one thing (`useCanvasComments` supplies the state).
 *
 * Design decisions: it is a `CanvasModeToggle` with the comment wording, so it looks and behaves like every other canvas mode
 * switch.
 */
import { useStrings } from "../context/TerminologyContext";
import { CanvasModeToggle } from "./CanvasModeToggle";

/**
 * @param on Whether comment mode is on.
 * @param onChange Called with the new state when the button is pressed.
 */
export function CommentModeToggle({ on, onChange }: { on: boolean; onChange: (next: boolean) => void }) {
  const text = useStrings().canvasComments;
  return <CanvasModeToggle label={text.modeLabel} help={text.modeHelp} on={on} onChange={onChange} />;
}
