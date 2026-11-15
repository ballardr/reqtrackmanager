/**
 * Module: modules/architecture/StateMachineSettingsButton
 *
 * The gear beside Export in the state machine editor's toolbar: a `SettingsPopoverButton` holding the viewer's own
 * display settings, Snap to grid (kept in this browser) and Always show attach points (kept in the person's account); neither is
 * stored with the diagram or applied to exports.
 */
import { AttachPointsSetting } from "../../components/AttachPointsSetting";
import { SettingsPopoverButton } from "../../components/SettingsPopoverButton";
import { SnapToGridSetting } from "../../components/SnapToGridSetting";

/**
 * @param snapToGrid Whether Snap to grid is on.
 * @param onSnapToGridChange Called with the new setting.
 * @param attachPointsAlways Whether attach points are always drawn (off: only near the pointer).
 * @param onAttachPointsAlwaysChange Called with the new setting.
 */
export function StateMachineSettingsButton({
  snapToGrid, onSnapToGridChange, attachPointsAlways, onAttachPointsAlwaysChange,
}: {
  snapToGrid: boolean;
  onSnapToGridChange: (next: boolean) => void;
  attachPointsAlways: boolean;
  onAttachPointsAlwaysChange: (next: boolean) => void;
}) {
  return (
    <SettingsPopoverButton
      label={`Diagram settings: snap to grid ${snapToGrid ? "on" : "off"}, attach points ${attachPointsAlways ? "always shown" : "near the pointer"}`}
      title="Diagram settings" marked={snapToGrid || attachPointsAlways}
    >
      <div className="stack" style={{ gap: "var(--space-2)" }}>
        <SnapToGridSetting checked={snapToGrid} onChange={onSnapToGridChange} />
        <AttachPointsSetting checked={attachPointsAlways} onChange={onAttachPointsAlwaysChange} />
      </div>
    </SettingsPopoverButton>
  );
}
