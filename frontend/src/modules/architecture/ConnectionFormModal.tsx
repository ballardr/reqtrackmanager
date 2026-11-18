/**
 * Module: modules/architecture/ConnectionFormModal
 *
 * Create and edit dialog for a connection between two elements, shared by the Connections list (create), the
 * detail page (edit), an element's page (create from that element) and told apart by whether `initial` is passed. The
 * two ends may be this project's elements or ones another owner shares with it (the caller passes both in `elements`);
 * a port is offered only when the chosen element has ports, and is cleared when the element changes. A new connection also takes quick
 * links, tags and "Save and activate" (a connection has no approval step).
 *
 * A new connection's Protocol starts as its type's default protocol and follows the type while the person has not set it; after
 * that a type change replaces it only while it is empty or still the previous type's default (`protocolAfterTypeChange`).
 *
 * The fields are the shared `ConnectionFieldGroup` (also the diagram Selection card's), whose type picker is guided, never
 * restrictive. A diagram adds a connection at once and edits it in its Selection card; this dialog opens there only when the
 * project has no connection type (`setupPath` then links to where types are set up) and, by a double click, to edit.
 */
import { useState } from "react";
import { Link } from "react-router-dom";

import type { CollectedLink } from "../../api/artefactLinks";
import { FormActions } from "../../components/FormActions";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { Modal } from "../../components/Modal";
import { QuickLinkField } from "../../components/QuickLinkField";
import { TagField } from "../../components/TagField";
import { blankConnectionValues, protocolAfterTypeChange, valuesFromConnection } from "./architectureFields";
import { ConnectionFieldGroup } from "./ConnectionFieldGroup";
import { defaultConnectionType } from "./connectionGuidance";
import type {
  ArchitectureConnection, ArchitectureDomain, ArchitectureElement, ConnectionFieldValues, ConnectionType, ElementType,
} from "./types";

/** What a new connection takes beyond the shared fields. */
export interface ConnectionCreateExtras {
  activate: boolean;
  quickLinks: CollectedLink[];
  tags: string[];
}

/**
 * @param initial The connection being edited; omit to create.
 * @param connectionTypes The types that may be chosen.
 * @param elementTypes The project's element types, which give each end's domain and suggested connection types; with
 *   none the picker offers every connection type.
 * @param domains The project's domains, whose names the mismatch warning uses.
 * @param elements Every element either end may be (the project's own and those shared with it).
 * @param projectId The connection's project, for quick links and tags.
 * @param defaultSourceId An element to preselect as the source of a new connection.
 * @param defaultTargetId An element to preselect as the target (a line drawn between two boxes of a diagram).
 * @param setupPath Where connection types are set up; shown as a link when the project has none.
 * @param error A save error to show.
 * @param onSave Called with the values and, for a new connection, the extras.
 */
export function ConnectionFormModal({
  initial, connectionTypes, elementTypes = [], domains, elements, projectId, defaultSourceId = "", defaultTargetId = "", setupPath, error,
  onCancel, onSave,
}: {
  initial?: ArchitectureConnection;
  connectionTypes: ConnectionType[];
  elementTypes?: ElementType[];
  domains?: ArchitectureDomain[];
  elements: ArchitectureElement[];
  projectId: string;
  defaultSourceId?: string;
  defaultTargetId?: string;
  setupPath?: string;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: ConnectionFieldValues, extras: ConnectionCreateExtras) => void;
}) {
  const [values, setValues] = useState<ConnectionFieldValues>(() =>
    initial ? valuesFromConnection(initial) : blankConnectionValues("", defaultSourceId, defaultTargetId));
  // A new connection's type follows the guidance until a type is chosen (`defaultConnectionType`).
  const [typeTouched, setTypeTouched] = useState(false);
  const [quickLinks, setQuickLinks] = useState<CollectedLink[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const [protocolTouched, setProtocolTouched] = useState(false);
  const typeById = (id: string) => connectionTypes.find((t) => t.id === id);

  const endType = (elementId: string): ElementType | undefined => {
    const typeId = elements.find((e) => e.id === elementId)?.element_type_id;
    return elementTypes.find((t) => t.id === typeId);
  };
  const typeId = initial || typeTouched
    ? values.connection_type_id
    : defaultConnectionType(connectionTypes, [endType(values.source_element_id), endType(values.target_element_id)])?.id ?? "";
  // A new connection shows its type's default protocol until the protocol or the type is set by the person.
  const protocol = initial || protocolTouched ? values.protocol : typeById(typeId)?.default_protocol ?? "";
  const set = <K extends keyof ConnectionFieldValues>(key: K, value: ConnectionFieldValues[K]) => {
    if (key === "connection_type_id") {
      setTypeTouched(true);
      setProtocolTouched(true);
      const next = protocolAfterTypeChange(protocol, typeById(typeId), typeById(value as string));
      setValues((prev) => ({ ...prev, connection_type_id: value as string, protocol: next }));
      return;
    }
    if (key === "protocol") setProtocolTouched(true);
    setValues((prev) => ({ ...prev, [key]: value }));
  };
  const valid = typeId !== "" && values.source_element_id !== "" && values.target_element_id !== ""
    && values.source_element_id !== values.target_element_id;

  function save(activate: boolean) {
    onSave({ ...values, connection_type_id: typeId, name: values.name.trim(), protocol: protocol.trim() }, { activate, quickLinks, tags });
  }

  return (
    <Modal title={initial ? `Edit ${initial.name || initial.unique_code}` : "New connection"} onClose={onCancel} size="lg">
      <div className="stack">
        {connectionTypes.length === 0 && (
          <p role="status">
            This project has no connection types, so a connection cannot be saved yet.
            {setupPath && <> <Link to={setupPath}>Set up connection types</Link>.</>}
          </p>
        )}
        <FormGrid minColumn="18rem">
          <ConnectionFieldGroup
            values={{ ...values, connection_type_id: typeId, protocol }} onChange={set} connectionTypes={connectionTypes}
            elementTypes={elementTypes} domains={domains} elements={elements} projectId={projectId} saved={initial}
          />
          {!initial && (
            <FormGridFull>
              <div className="stack">
                <QuickLinkField projectId={projectId} artefactType="architecture_connection" value={quickLinks} onChange={setQuickLinks} />
                <TagField projectId={projectId} artefactType="architecture_connection" value={tags} onChange={setTags} />
              </div>
            </FormGridFull>
          )}
        </FormGrid>
        <FormActions
          error={error} onCancel={onCancel} onSave={() => save(false)} saveDisabled={!valid}
          onSaveAndActivate={initial ? undefined : () => save(true)}
        />
      </div>
    </Modal>
  );
}
