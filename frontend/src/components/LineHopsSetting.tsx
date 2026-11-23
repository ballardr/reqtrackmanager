/**
 * Module: components/LineHopsSetting
 *
 * The Line hops row of a canvas editor's settings: a switch and its help. The setting belongs to the diagram
 * (every viewer and export draws the same arcs), so each editor stores it on its own record; this is the one
 * control, so every editor words it the same way.
 */
import { useStrings } from "../context/TerminologyContext";
import { FieldCaption } from "./FieldHelp";
import { ToggleSwitch } from "./ToggleSwitch";

/**
 * @param checked Whether a line that crosses another is drawn with a small arc over it.
 * @param disabled True when the setting cannot be changed (a read-only diagram, or a save in progress).
 * @param onChange Called with the new setting.
 */
export function LineHopsSetting({ checked, disabled, onChange }: { checked: boolean; disabled?: boolean; onChange: (next: boolean) => void }) {
  const text = useStrings().graphCanvas;
  return (
    <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
      <ToggleSwitch checked={checked} disabled={disabled} label={text.lineHopsLabel} onChange={onChange} />
      <FieldCaption label={text.lineHopsLabel} help={text.lineHopsHelp} />
    </span>
  );
}
