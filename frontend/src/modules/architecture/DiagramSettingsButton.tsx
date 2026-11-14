/**
 * Module: modules/architecture/DiagramSettingsButton
 *
 * The gear beside Export in the editor toolbar: a `SettingsPopoverButton` holding the diagram-level setting that is
 * stored when changed (the connection-detail switch, which sets whether the diagram draws plain lines or typed,
 * labelled ones; it belongs to the diagram and applies to every viewer) and the viewer's own display switches: Show
 * notes (whether a box draws its display note; kept in the page address), and Show comments and Show resolved (whether the
 * comment markers, and those of resolved threads, are drawn). None of the three is stored or applied to exports.
 */
import { FieldCaption } from "../../components/FieldHelp";
import { SettingsPopoverButton } from "../../components/SettingsPopoverButton";
import { ToggleSwitch } from "../../components/ToggleSwitch";
import { useStrings } from "../../context/TerminologyContext";
import { ARCHITECTURE_HELP } from "./help";

/**
 * @param connectionDetail Whether the diagram draws connection detail.
 * @param disabled True when the settings cannot be changed (read-only diagram, or a save in progress).
 * @param onConnectionDetailChange Called with the new connection-detail setting.
 * @param showNotes Whether boxes draw their display notes on this screen.
 * @param onShowNotesChange Called with the new Show notes choice (never disabled: it changes only this viewer's screen).
 * @param showComments Whether comment markers are drawn on this screen.
 * @param onShowCommentsChange Called with the new Show comments choice.
 * @param showResolved Whether markers of resolved threads are drawn.
 * @param onShowResolvedChange Called with the new Show resolved choice.
 */
export function DiagramSettingsButton({
  connectionDetail, disabled, onConnectionDetailChange, showNotes, onShowNotesChange, showComments, onShowCommentsChange,
  showResolved, onShowResolvedChange,
}: {
  connectionDetail: boolean;
  disabled: boolean;
  onConnectionDetailChange: (next: boolean) => void;
  showNotes: boolean;
  onShowNotesChange: (next: boolean) => void;
  showComments: boolean;
  onShowCommentsChange: (next: boolean) => void;
  showResolved: boolean;
  onShowResolvedChange: (next: boolean) => void;
}) {
  const text = useStrings().canvasComments;
  return (
    <SettingsPopoverButton
      label={`Diagram settings: connection detail ${connectionDetail ? "on" : "off"}, notes ${showNotes ? "shown" : "hidden"}, comments ${showComments ? "shown" : "hidden"}`}
      title="Diagram settings" marked={connectionDetail || !showNotes || !showComments}
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
        <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
          <ToggleSwitch checked={showComments} label={text.showComments} onChange={onShowCommentsChange} />
          <FieldCaption label={text.showComments} help={text.showCommentsHelp} />
        </span>
        <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
          <ToggleSwitch checked={showResolved} disabled={!showComments} label={text.showResolved} onChange={onShowResolvedChange} />
          <FieldCaption label={text.showResolved} help={text.showResolvedHelp} />
        </span>
      </div>
    </SettingsPopoverButton>
  );
}
