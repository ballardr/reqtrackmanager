/**
 * Module: modules/architecture/PortList
 *
 * The ports of an element as an editable list on the shared `DefinitionList`: a name, a direction and an optional
 * connection type per port. The element form holds the list in memory until the element is saved and the detail page
 * saves each change at once, so the component only reports what the person did (`onAdd`, `onChange`, `onRemove`) and
 * the caller decides what that means. Direction is shown through `PORT_DIRECTION_LABEL`.
 */
import { DefinitionList } from "../../components/DefinitionList";
import { InlineSelect } from "../../components/LabeledSelect";
import { labelOptions } from "../../utils/labelOptions";
import { PORT_DIRECTION_LABEL, type ConnectionType, type Port, type PortDirection, type PortValues } from "./types";

/** A port as the list shows it; `id` is the server's, or a temporary one for a port not saved yet. */
export type PortRow = Pick<Port, "id" | "name" | "direction" | "connection_type_id">;

/**
 * @param ports The ports to show.
 * @param connectionTypes The connection types a port may name.
 * @param readOnly Shows the ports without controls (an element shared from another owner).
 * @param onAdd Called with a new port's values (name from the add row; direction "Both" and no type, to adjust in the row).
 * @param onChange Called with a port's id and the one field that changed.
 * @param onRemove Called with the id of the port to remove.
 */
export function PortList({
  ports, connectionTypes, readOnly = false, onAdd, onChange, onRemove,
}: {
  ports: PortRow[];
  connectionTypes: ConnectionType[];
  readOnly?: boolean;
  onAdd: (values: PortValues) => Promise<void>;
  onChange: (id: string, change: Partial<PortValues>) => Promise<void>;
  onRemove: (id: string) => Promise<void>;
}) {
  if (readOnly) {
    return ports.length === 0 ? <p className="text-muted">No ports.</p> : (
      <ul style={{ margin: 0, paddingLeft: "var(--space-4)" }}>
        {ports.map((p) => (
          <li key={p.id}>{p.name} · {PORT_DIRECTION_LABEL[p.direction]}</li>
        ))}
      </ul>
    );
  }
  return (
    <DefinitionList<PortRow>
      layout="grid"
      items={ports}
      fields={[{ key: "name", getValue: (p) => p.name, label: "Name", placeholder: "Port name", ariaLabel: "Port name", track: "minmax(8rem, 1fr)" }]}
      getReassignLabel={(p) => p.name}
      minItems={0}
      onRename={(id, values) => onChange(id, { name: values.name })}
      onAdd={(values) => onAdd({ name: values.name, direction: "both", connection_type_id: null })}
      onDelete={onRemove}
      deleteLabel="Remove port"
      addLabel="Add port"
      renderExtra={(port) => (
        <span key="port-extra" className="row" style={{ gap: "var(--space-2)" }}>
          <InlineSelect<PortDirection>
            ariaLabel={`Direction of ${port.name}`} value={port.direction} placeholder={null} autoWidth
            options={labelOptions(PORT_DIRECTION_LABEL)}
            onChange={(next) => void onChange(port.id, { direction: next })}
          />
          <InlineSelect
            ariaLabel={`Connection type of ${port.name}`} value={port.connection_type_id ?? ""} placeholder="Any type" autoWidth
            options={connectionTypes.map((t) => ({ value: t.id, label: t.name }))}
            onChange={(next) => void onChange(port.id, { connection_type_id: next || null })}
          />
        </span>
      )}
    />
  );
}
