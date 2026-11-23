/**
 * Module: components/CommentModeToggle
 *
 * The toolbar switch for a graph canvas's comment mode, shared by every editor that comments on a canvas
 * (`useCanvasComments` supplies the state). It is a `CanvasModeToggle` with the comment wording.
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
