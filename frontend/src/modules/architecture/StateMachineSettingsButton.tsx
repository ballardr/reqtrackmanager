/**
 * Module: modules/architecture/StateMachineSettingsButton
 *
 * The gear beside Export in the state machine editor's toolbar: a `SettingsPopoverButton` holding the diagram-level Line hops
 * switch (stored when changed; it belongs to the diagram and applies to every viewer and every export) and the viewer's own
 * display settings, Snap to grid (kept in this browser) and Always show attach points (kept in the person's account); neither
 * of these is stored with the diagram or applied to exports.
 */
import { AttachPointsSetting } from "../../components/AttachPointsSetting";
import { LineHopsSetting } from "../../components/LineHopsSetting";
import { SettingsPopoverButton } from "../../components/SettingsPopoverButton";
import { SnapToGridSetting } from "../../components/SnapToGridSetting";

/**
 * @param lineHops Whether the diagram draws a small arc where a transition crosses another.
 * @param disabled True when Line hops cannot be changed (a read-only diagram, or a save in progress).
 * @param onLineHopsChange Called with the new Line hops setting.
 * @param snapToGrid Whether Snap to grid is on.
 * @param onSnapToGridChange Called with the new setting.
 * @param attachPointsAlways Whether attach points are always drawn (off: only near the pointer).
 * @param onAttachPointsAlwaysChange Called with the new setting.
 */
export function StateMachineSettingsButton({
  lineHops, disabled, onLineHopsChange, snapToGrid, onSnapToGridChange, attachPointsAlways, onAttachPointsAlwaysChange,
}: {
  lineHops: boolean;
  disabled: boolean;
  onLineHopsChange: (next: boolean) => void;
  snapToGrid: boolean;
  onSnapToGridChange: (next: boolean) => void;
  attachPointsAlways: boolean;
  onAttachPointsAlwaysChange: (next: boolean) => void;
}) {
  return (
    <SettingsPopoverButton
      label={`Diagram settings: line hops ${lineHops ? "on" : "off"}, snap to grid ${snapToGrid ? "on" : "off"}, attach points ${attachPointsAlways ? "always shown" : "near the pointer"}`}
      title="Diagram settings" marked={lineHops || snapToGrid || attachPointsAlways}
    >
      <div className="stack" style={{ gap: "var(--space-2)" }}>
        <LineHopsSetting checked={lineHops} disabled={disabled} onChange={onLineHopsChange} />
        <SnapToGridSetting checked={snapToGrid} onChange={onSnapToGridChange} />
        <AttachPointsSetting checked={attachPointsAlways} onChange={onAttachPointsAlwaysChange} />
      </div>
    </SettingsPopoverButton>
  );
}
