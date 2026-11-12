/**
 * Module: modules/architecture/DiagramConnectionDetailPanel
 *
 * The Configuration tab's "Connections" card: the switch that sets whether the diagram draws plain lines or typed,
 * labelled ones (`connection_detail`). The setting is stored when changed, unlike the view switches' on-page state.
 */
import { DetailCard } from "../../components/DetailCard";
import { FieldCaption } from "../../components/FieldHelp";
import { ToggleSwitch } from "../../components/ToggleSwitch";
import { ARCHITECTURE_HELP } from "./help";

/**
 * @param checked Whether the diagram draws connection detail.
 * @param disabled True when the setting cannot be changed (read-only diagram, or a save in progress).
 * @param onChange Called with the new setting.
 */
export function DiagramConnectionDetailPanel({
  checked, disabled, onChange,
}: { checked: boolean; disabled: boolean; onChange: (next: boolean) => void }) {
  return (
    <DetailCard heading="Connections">
      <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
        <ToggleSwitch checked={checked} disabled={disabled} label="Connection detail" onChange={onChange} />
        <FieldCaption label="Connection detail" help={ARCHITECTURE_HELP.diagramConnectionDetail} />
      </span>
    </DetailCard>
  );
}
