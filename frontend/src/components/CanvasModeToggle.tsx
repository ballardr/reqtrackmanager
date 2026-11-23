/**
 * Module: components/CanvasModeToggle
 *
 * The toolbar switch for one mode of a graph canvas in which a click does something other than select (comment
 * mode, note mode): one component so the pressed look, height and tooltip are one thing. The help is the button's
 * own tooltip, one line per state (docs/ux-style-guide.md, "Pattern: help on interactive elements"). Only one
 * mode is on at a time: the editor turns the others off when it turns one on.
 */
import { ToggleButton } from "./ToggleButton";

/**
 * @param label The mode's name, shown on the button and used as its accessible name.
 * @param help What the mode does, one line per state ("On: ...", "Off: ...").
 * @param on Whether the mode is on.
 * @param onChange Called with the new state when the button is pressed.
 * @param disabled Disables the switch (a read-only editor).
 */
export function CanvasModeToggle({
  label, help, on, onChange, disabled,
}: { label: string; help: string; on: boolean; onChange: (next: boolean) => void; disabled?: boolean }) {
  return (
    <ToggleButton label={label} iconOnly={false} pressed={on} help={help} disabled={disabled} onClick={() => onChange(!on)}>
      {label}
    </ToggleButton>
  );
}
