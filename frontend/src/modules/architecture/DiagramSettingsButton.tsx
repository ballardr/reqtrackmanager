/**
 * Module: modules/architecture/DiagramSettingsButton
 *
 * The gear beside Export in the editor toolbar: a `SettingsPopoverButton` holding the diagram-level settings, stored
 * when changed (the connection-detail switch for plain or typed, labelled lines; Line hops, which draws a crossing line
 * with a small arc; Show connection names; and the default line shape; all apply to every viewer and every export), and
 * the viewer's own display switches: Show notes (kept in the page address), Show comments and Show resolved (whether
 * comment markers, and those of resolved threads, are drawn), Snap to grid (kept in this browser) and Always show
 * attach points (kept in the person's account). None of these five is stored with the diagram or applied to exports.
 */
import { AttachPointsSetting } from "../../components/AttachPointsSetting";
import { FieldCaption } from "../../components/FieldHelp";
import { LineHopsSetting } from "../../components/LineHopsSetting";
import { LineShapeSelect } from "../../components/LineShapeSelect";
import type { LineShape } from "../../components/graphLinePath";
import { SettingsPopoverButton } from "../../components/SettingsPopoverButton";
import { SnapToGridSetting } from "../../components/SnapToGridSetting";
import { ToggleSwitch } from "../../components/ToggleSwitch";
import { useStrings } from "../../context/TerminologyContext";
import { ARCHITECTURE_HELP } from "./help";

/**
 * @param connectionDetail Whether the diagram draws connection detail.
 * @param disabled True when the settings cannot be changed (read-only diagram, or a save in progress).
 * @param onConnectionDetailChange Called with the new connection-detail setting.
 * @param lineHops Whether the diagram draws a small arc where a line crosses another.
 * @param onLineHopsChange Called with the new Line hops setting.
 * @param showConnectionNames Whether a line is labelled with the names of its connections.
 * @param onShowConnectionNamesChange Called with the new Show connection names setting.
 * @param lineShape How a line or leader with no shape of its own is drawn.
 * @param onLineShapeChange Called with the new default shape.
 * @param showNotes Whether boxes draw their display notes on this screen.
 * @param onShowNotesChange Called with the new Show notes choice (never disabled: it changes only this viewer's screen).
 * @param showComments Whether comment markers are drawn on this screen.
 * @param onShowCommentsChange Called with the new Show comments choice.
 * @param showResolved Whether markers of resolved threads are drawn.
 * @param onShowResolvedChange Called with the new Show resolved choice.
 * @param snapToGrid Whether Snap to grid is on.
 * @param onSnapToGridChange Called with the new Snap to grid setting.
 * @param attachPointsAlways Whether attach points are always drawn (off: only near the pointer).
 * @param onAttachPointsAlwaysChange Called with the new setting.
 */
export function DiagramSettingsButton({
  connectionDetail, disabled, onConnectionDetailChange, lineHops, onLineHopsChange, showConnectionNames, onShowConnectionNamesChange, lineShape, onLineShapeChange, showNotes, onShowNotesChange, showComments, onShowCommentsChange,
  showResolved, onShowResolvedChange, snapToGrid, onSnapToGridChange, attachPointsAlways, onAttachPointsAlwaysChange,
}: {
  connectionDetail: boolean;
  disabled: boolean;
  onConnectionDetailChange: (next: boolean) => void;
  lineHops: boolean;
  onLineHopsChange: (next: boolean) => void;
  showConnectionNames: boolean;
  onShowConnectionNamesChange: (next: boolean) => void;
  lineShape: LineShape;
  onLineShapeChange: (next: LineShape) => void;
  showNotes: boolean;
  onShowNotesChange: (next: boolean) => void;
  showComments: boolean;
  onShowCommentsChange: (next: boolean) => void;
  showResolved: boolean;
  onShowResolvedChange: (next: boolean) => void;
  snapToGrid: boolean;
  onSnapToGridChange: (next: boolean) => void;
  attachPointsAlways: boolean;
  onAttachPointsAlwaysChange: (next: boolean) => void;
}) {
  const text = useStrings().canvasComments;
  return (
    <SettingsPopoverButton
      label={`Diagram settings: connection detail ${connectionDetail ? "on" : "off"}, line hops ${lineHops ? "on" : "off"}, connection names ${showConnectionNames ? "on" : "off"}, notes ${showNotes ? "shown" : "hidden"}, comments ${showComments ? "shown" : "hidden"}, snap to grid ${snapToGrid ? "on" : "off"}, attach points ${attachPointsAlways ? "always shown" : "near the pointer"}${lineShape === "straight" ? "" : `, line shape ${lineShape}`}`}
      title="Diagram settings" marked={connectionDetail || lineHops || showConnectionNames || lineShape !== "straight" || !showNotes || !showComments || snapToGrid || attachPointsAlways}
    >
      <div className="stack" style={{ gap: "var(--space-2)" }}>
        <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
          <ToggleSwitch checked={connectionDetail} disabled={disabled} label="Connection detail" onChange={onConnectionDetailChange} />
          <FieldCaption label="Connection detail" help={ARCHITECTURE_HELP.diagramConnectionDetail} />
        </span>
        <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
          <ToggleSwitch checked={showConnectionNames} disabled={disabled} label="Show connection names" onChange={onShowConnectionNamesChange} />
          <FieldCaption label="Show connection names" help={ARCHITECTURE_HELP.diagramShowConnectionNames} />
        </span>
        <LineHopsSetting checked={lineHops} disabled={disabled} onChange={onLineHopsChange} />
        <LineShapeSelect value={lineShape} disabled={disabled} onChange={(next) => { if (next) onLineShapeChange(next); }} />
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
        <SnapToGridSetting checked={snapToGrid} onChange={onSnapToGridChange} />
        <AttachPointsSetting checked={attachPointsAlways} onChange={onAttachPointsAlwaysChange} />
      </div>
    </SettingsPopoverButton>
  );
}
