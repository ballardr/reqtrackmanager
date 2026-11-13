/**
 * Module: modules/architecture/DiagramSettingsButton
 *
 * The gear beside Export in the editor toolbar: a `SettingsPopoverButton` holding the diagram-level setting that is
 * stored when changed (the connection-detail switch, which sets whether the diagram draws plain lines or typed,
 * labelled ones; it belongs to the diagram and applies to every viewer) and the viewer's own Show notes switch (whether
 * a box draws its display note on this screen; kept in the page address, never stored, and not applied to exports).
 */
import { FieldCaption } from "../../components/FieldHelp";
import { SettingsPopoverButton } from "../../components/SettingsPopoverButton";
import { ToggleSwitch } from "../../components/ToggleSwitch";
import { ARCHITECTURE_HELP } from "./help";

/**
 * @param connectionDetail Whether the diagram draws connection detail.
 * @param disabled True when the settings cannot be changed (read-only diagram, or a save in progress).
 * @param onConnectionDetailChange Called with the new connection-detail setting.
 * @param showNotes Whether boxes draw their display notes on this screen.
 * @param onShowNotesChange Called with the new Show notes choice (never disabled: it changes only this viewer's screen).
 */
export function DiagramSettingsButton({
  connectionDetail, disabled, onConnectionDetailChange, showNotes, onShowNotesChange,
}: {
  connectionDetail: boolean;
  disabled: boolean;
  onConnectionDetailChange: (next: boolean) => void;
  showNotes: boolean;
  onShowNotesChange: (next: boolean) => void;
}) {
  return (
    <SettingsPopoverButton
      label={`Diagram settings: connection detail ${connectionDetail ? "on" : "off"}, notes ${showNotes ? "shown" : "hidden"}`}
      title="Diagram settings" marked={connectionDetail || !showNotes}
    >
      <div className="stack" style={{ gap: "var(--space-2)" }}>
        <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
          <ToggleSwitch checked={connectionDetail} disabled={disabled} label="Connection detail" onChange={onConnectionDetailChange} />
          <FieldCaption label="Connection detail" help={ARCHITECTURE_HELP.diagramConnectionDetail} />
        </span>
        <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
          <ToggleSwitch checked={showNotes} label="Show notes" onChange={onShowNotesChange} />
          <FieldCaption label="Show notes" help={ARCHITECTURE_HELP.diagramShowNotes} />
        </span>
      </div>
    </SettingsPopoverButton>
  );
}
