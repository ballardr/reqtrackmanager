/**
 * Module: modules/architecture/DiagramSettingsButton
 *
 * The gear beside Export in the editor toolbar: a `SettingsPopoverButton` holding the diagram-level settings that are
 * stored when changed (today the connection-detail switch, which sets whether the diagram draws plain lines or typed,
 * labelled ones). Unlike the view switches on the Configuration tab, these belong to the diagram and apply to every viewer.
 */
import { FieldCaption } from "../../components/FieldHelp";
import { SettingsPopoverButton } from "../../components/SettingsPopoverButton";
import { ToggleSwitch } from "../../components/ToggleSwitch";
import { ARCHITECTURE_HELP } from "./help";

/**
 * @param connectionDetail Whether the diagram draws connection detail.
 * @param disabled True when the settings cannot be changed (read-only diagram, or a save in progress).
 * @param onConnectionDetailChange Called with the new connection-detail setting.
 */
export function DiagramSettingsButton({
  connectionDetail, disabled, onConnectionDetailChange,
}: { connectionDetail: boolean; disabled: boolean; onConnectionDetailChange: (next: boolean) => void }) {
  return (
    <SettingsPopoverButton
      label={`Diagram settings: connection detail ${connectionDetail ? "on" : "off"}`} title="Diagram settings" marked={connectionDetail}
    >
      <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
        <ToggleSwitch checked={connectionDetail} disabled={disabled} label="Connection detail" onChange={onConnectionDetailChange} />
        <FieldCaption label="Connection detail" help={ARCHITECTURE_HELP.diagramConnectionDetail} />
      </span>
    </SettingsPopoverButton>
  );
}
