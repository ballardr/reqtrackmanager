/**
 * Module: modules/architecture/StateMachineSettingsButton
 *
 * The gear beside Export in the state machine editor's toolbar: a `SettingsPopoverButton` holding the viewer's own
 * display setting, Snap to grid (kept in this browser, not stored with the diagram and not applied to exports).
 */
import { SettingsPopoverButton } from "../../components/SettingsPopoverButton";
import { SnapToGridSetting } from "../../components/SnapToGridSetting";

/**
 * @param snapToGrid Whether Snap to grid is on.
 * @param onSnapToGridChange Called with the new setting.
 */
export function StateMachineSettingsButton({ snapToGrid, onSnapToGridChange }: { snapToGrid: boolean; onSnapToGridChange: (next: boolean) => void }) {
  return (
    <SettingsPopoverButton label={`Diagram settings: snap to grid ${snapToGrid ? "on" : "off"}`} title="Diagram settings" marked={snapToGrid}>
      <div className="stack" style={{ gap: "var(--space-2)" }}>
        <SnapToGridSetting checked={snapToGrid} onChange={onSnapToGridChange} />
      </div>
    </SettingsPopoverButton>
  );
}
