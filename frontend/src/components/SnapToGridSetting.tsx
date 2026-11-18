/**
 * Module: components/SnapToGridSetting
 *
 * The Snap to grid row of a canvas editor's settings: a switch and its captioned help. It is the one control behind the
 * shared preference (`hooks/useSnapToGrid`), so every editor words it the same way.
 */
import { useStrings } from "../context/TerminologyContext";
import { FieldCaption } from "./FieldHelp";
import { ToggleSwitch } from "./ToggleSwitch";

/**
 * @param checked Whether snapping is on.
 * @param onChange Called with the new setting.
 */
export function SnapToGridSetting({ checked, onChange }: { checked: boolean; onChange: (next: boolean) => void }) {
  const text = useStrings().graphCanvas;
  return (
    <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
      <ToggleSwitch checked={checked} label={text.snapLabel} onChange={onChange} />
      <FieldCaption label={text.snapLabel} help={text.snapHelp} />
    </span>
  );
}
