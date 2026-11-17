/**
 * Module: modules/architecture/ConnectionSelectionFields
 *
 * The Selection card's editable view of the one connection a line stands for: the shared field group (`ConnectionFieldGroup`,
 * also the create and edit dialogs') edited in place and stored when the focus leaves the group or Save is pressed, quoting the
 * connection's version. Both ends and a type are required, so a draft that empties one is not stored and says so; another save's
 * changes to a field the person has not touched are taken in.
 *
 * Design decisions:
 * - The draft and its commit are the shared `useSelectionDraft`; a connection is stored at once, not with the drawing.
 * - A line that stands for several connections (rolled up or merged) is not edited here: each row of its table opens the dialog.
 * - The Save button is always present and disabled while nothing has changed, so the card does not change size as the person types.
 */
import { useEffect, useRef } from "react";

import { FormGrid } from "../../components/FormGrid";
import { useLatest } from "../../hooks/useLatest";
import { diffConnectionFields, protocolAfterTypeChange, valuesFromConnection } from "./architectureFields";
import { ConnectionFieldGroup } from "./ConnectionFieldGroup";
import type {
  ArchitectureConnection, ArchitectureDomain, ArchitectureElement, ConnectionFieldValues, ConnectionType, ElementType,
} from "./types";
import { useSelectionDraft } from "./useSelectionDraft";

/**
 * @param connection The connection as last read.
 * @param connectionTypes The types that may be chosen.
 * @param elementTypes The project's element types (each end's domain and suggested connection types).
 * @param domains The project's domains, whose names the mismatch warning uses.
 * @param elements Every element either end may be.
 * @param projectId The connection's project.
 * @param autoFocusName True to select the name when the card first appears (a connection just added).
 * @param onFocused Called once the name has taken the focus, so the request is not repeated.
 * @param onSave Stores the changed fields; resolves true when stored.
 */
export function ConnectionSelectionFields({
  connection, connectionTypes, elementTypes, domains, elements, projectId, autoFocusName, onFocused, onSave,
}: {
  connection: ArchitectureConnection;
  connectionTypes: ConnectionType[];
  elementTypes: ElementType[];
  domains?: ArchitectureDomain[];
  elements: ArchitectureElement[];
  projectId: string;
  autoFocusName: boolean;
  onFocused: () => void;
  onSave: (changed: Partial<ConnectionFieldValues>) => Promise<boolean>;
}) {
  const { draft, set, hasChanges, refused, commit } = useSelectionDraft<ConnectionFieldValues>({
    stored: valuesFromConnection(connection), diff: diffConnectionFields,
    normalise: (v) => ({ ...v, name: v.name.trim(), protocol: v.protocol.trim() }),
    refuse: (v) => v.connection_type_id === "" || v.source_element_id === "" || v.target_element_id === "" || v.source_element_id === v.target_element_id,
    onSave,
  });
  // Changing the type also moves the protocol when it was empty or still the previous type's default.
  const setField: typeof set = (key, value) => {
    if (key === "connection_type_id") {
      const typeOf = (id: string) => connectionTypes.find((t) => t.id === id);
      set("protocol", protocolAfterTypeChange(draft.protocol, typeOf(draft.connection_type_id), typeOf(value as string)));
    }
    set(key, value);
  };
  const focusDone = useLatest(onFocused);
  const askedFocus = useRef(autoFocusName);
  useEffect(() => { if (askedFocus.current) focusDone.current(); }, [focusDone]);

  return (
    <div
      className="stack" role="group" aria-label="Connection details"
      onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) void commit(); }}
    >
      <FormGrid minColumn="14rem">
        <ConnectionFieldGroup
          values={draft} onChange={setField} connectionTypes={connectionTypes} elementTypes={elementTypes} domains={domains} elements={elements}
          projectId={projectId} saved={connection} autoFocusName={autoFocusName}
        />
      </FormGrid>
      {refused && <p role="alert" style={{ color: "var(--color-danger)" }}>A connection needs a type and two different elements.</p>}
      <button
        type="button" className="btn btn-sm" style={{ alignSelf: "flex-start" }}
        disabled={!hasChanges} onClick={() => void commit()} aria-label="Save connection"
      >
        Save
      </button>
    </div>
  );
}
