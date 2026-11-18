/**
 * Module: components/AttachPointsSetting
 *
 * The "Always show attach points" row of a canvas editor's settings: a switch and its captioned help. It is the one control
 * behind the shared preference (`hooks/useAttachPointVisibility`), so every editor words it the same way.
 */
import { useStrings } from "../context/TerminologyContext";
import { FieldCaption } from "./FieldHelp";
import { ToggleSwitch } from "./ToggleSwitch";

/**
 * @param checked Whether attach points are always drawn (off: only near the pointer).
 * @param onChange Called with the new setting.
 */
export function AttachPointsSetting({ checked, onChange }: { checked: boolean; onChange: (next: boolean) => void }) {
  const text = useStrings().graphCanvas;
  return (
    <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
      <ToggleSwitch checked={checked} label={text.attachPointsLabel} onChange={onChange} />
      <FieldCaption label={text.attachPointsLabel} help={text.attachPointsHelp} />
    </span>
  );
}
