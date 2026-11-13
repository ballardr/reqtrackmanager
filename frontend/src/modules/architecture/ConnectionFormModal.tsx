/**
 * Module: modules/architecture/ConnectionFormModal
 *
 * Create and edit dialog for a connection between two elements, shared by the Connections list (create), the
 * detail page (edit), an element's page (create from that element) and told apart by whether `initial` is passed. The
 * two ends may be this project's elements or ones another owner shares with it (the caller passes both in `elements`);
 * a port is offered only when the chosen element has ports, and is cleared when the element changes. A new connection also takes quick
 * links, tags and "Save and activate" (a connection has no approval step).
 *
 * The type picker is guided, never restrictive (`connectionGuidance`): it lists the types whose domain fits both ends,
 * with the types suggested for the ends' element types first, offers every type on "Show all types", and warns when
 * a type that does not fit is chosen.
 */
import { useState } from "react";

import type { CollectedLink } from "../../api/artefactLinks";
import { FormActions } from "../../components/FormActions";
import { TextAreaField, TextField } from "../../components/FormFields";
import { ToggleField } from "../../components/FormFields";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { TreeSelectField } from "../../components/TreeSelectField";
import { QuickLinkField } from "../../components/QuickLinkField";
import { TagField } from "../../components/TagField";
import { useRecordCode } from "../../hooks/useRecordCode";
import { blankConnectionValues, valuesFromConnection } from "./architectureFields";
import { guideConnectionTypes, mismatchWarning, suggestedGroup } from "./connectionGuidance";
import { connectionTypeNodes } from "./connectionTypeTree";
import { FolderField } from "./FolderField";
import { ARCHITECTURE_HELP } from "./help";
import type { ArchitectureConnection, ArchitectureElement, ConnectionFieldValues, ConnectionType, ElementType } from "./types";
import { isOutOfUse } from "./types";

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
 * @param elements Every element either end may be (the project's own and those shared with it).
 * @param projectId The connection's project, for quick links and tags.
 * @param defaultSourceId An element to preselect as the source of a new connection.
 * @param defaultTargetId An element to preselect as the target (a line drawn between two boxes of a diagram).
 * @param error A save error to show.
 * @param onSave Called with the values and, for a new connection, the extras.
 */
export function ConnectionFormModal({
  initial, connectionTypes, elementTypes = [], elements, projectId, defaultSourceId = "", defaultTargetId = "", error, onCancel,
  onSave,
}: {
  initial?: ArchitectureConnection;
  connectionTypes: ConnectionType[];
  elementTypes?: ElementType[];
  elements: ArchitectureElement[];
  projectId: string;
  defaultSourceId?: string;
  defaultTargetId?: string;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: ConnectionFieldValues, extras: ConnectionCreateExtras) => void;
}) {
  const formatCode = useRecordCode();
  const [values, setValues] = useState<ConnectionFieldValues>(() =>
    initial ? valuesFromConnection(initial) : blankConnectionValues("", defaultSourceId, defaultTargetId));
  // A new connection's type follows the guidance until a type is chosen: the first type its ends suggest, else the first
  // that fits both.
  const [typeTouched, setTypeTouched] = useState(false);
  const [quickLinks, setQuickLinks] = useState<CollectedLink[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const [showAll, setShowAll] = useState(false);
  const set = <K extends keyof ConnectionFieldValues>(key: K, value: ConnectionFieldValues[K]) =>
    setValues((prev) => ({ ...prev, [key]: value }));

  const options = elements.filter((e) => !isOutOfUse(e.status) || e.id === initial?.source_element_id || e.id === initial?.target_element_id);
  const elementOptions = options.map((e) => ({
    value: e.id, label: `${formatCode.code(e.unique_code, e.from_project_code)} ${e.name}${e.shared ? " (shared)" : ""}`,
  }));
  const portOptions = (elementId: string) =>
    (elements.find((e) => e.id === elementId)?.ports ?? []).map((p) => ({ value: p.id, label: p.name }));
  const endType = (elementId: string): ElementType | undefined => {
    const typeId = elements.find((e) => e.id === elementId)?.element_type_id;
    return elementTypes.find((t) => t.id === typeId);
  };
  const ends = [endType(values.source_element_id), endType(values.target_element_id)];
  const guidance = guideConnectionTypes(connectionTypes, ends);
  const typeId = initial || typeTouched
    ? values.connection_type_id
    : (guidance.suggested[0] ?? guidance.offered[0] ?? connectionTypes[0])?.id ?? "";
  const chosen = connectionTypes.find((t) => t.id === typeId);
  // A chosen type stays in the list even when the domain filter would hide it, so the picker never loses the choice.
  const stillHidden = guidance.hidden.filter((t) => t.id !== typeId);
  const listed = showAll || stillHidden.length === 0
    ? connectionTypes
    : connectionTypes.filter((t) => guidance.offered.includes(t) || t.id === typeId);
  const typeNodes = [...suggestedGroup(guidance.suggested), ...connectionTypeNodes(listed)];
  const warning = mismatchWarning(chosen, ends);
  const valid = typeId !== "" && values.source_element_id !== "" && values.target_element_id !== ""
    && values.source_element_id !== values.target_element_id;

  function save(activate: boolean) {
    onSave({ ...values, connection_type_id: typeId, name: values.name.trim(), protocol: values.protocol.trim() }, { activate, quickLinks, tags });
  }

  return (
    <Modal title={initial ? `Edit ${initial.name || initial.unique_code}` : "New connection"} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <FormGridFull>
            <TextField helpNotNeeded label="Name" value={values.name} onChange={(value) => set("name", value)} />
          </FormGridFull>
          <div className="stack">
            <TreeSelectField
              help={ARCHITECTURE_HELP.connectionType} required single searchable label="Connection type"
              value={typeId ? [typeId] : []} emptyLabel="Choose a type"
              nodes={typeNodes} onChange={([next]) => { setTypeTouched(true); set("connection_type_id", next ?? ""); }}
            />
            {(showAll || stillHidden.length > 0) && (
              <ToggleField
                help={ARCHITECTURE_HELP.connectionTypeShowAll} label="Show all types" checked={showAll}
                onChange={setShowAll} hint={showAll ? undefined : `${stillHidden.length} hidden`}
              />
            )}
            {warning && <p role="status" style={{ margin: 0, color: "var(--color-warning)" }}>{warning}</p>}
          </div>
          <TextField help={ARCHITECTURE_HELP.connectionProtocol} label="Protocol" value={values.protocol} onChange={(value) => set("protocol", value)} />
          <LabeledSelect
            help={ARCHITECTURE_HELP.connectionSource} required label="Source element" value={values.source_element_id}
            placeholder="Choose an element" options={elementOptions}
            onChange={(next) => setValues((prev) => ({ ...prev, source_element_id: next, source_port_id: null }))}
          />
          {portOptions(values.source_element_id).length > 0 && (
            <LabeledSelect
              help={ARCHITECTURE_HELP.connectionPort} label="Source port" value={values.source_port_id ?? ""} placeholder="No port"
              options={portOptions(values.source_element_id)} onChange={(next) => set("source_port_id", next || null)}
            />
          )}
          <LabeledSelect
            help={ARCHITECTURE_HELP.connectionTarget} required label="Target element" value={values.target_element_id}
            placeholder="Choose an element" options={elementOptions}
            onChange={(next) => setValues((prev) => ({ ...prev, target_element_id: next, target_port_id: null }))}
          />
          {portOptions(values.target_element_id).length > 0 && (
            <LabeledSelect
              help={ARCHITECTURE_HELP.connectionPort} label="Target port" value={values.target_port_id ?? ""} placeholder="No port"
              options={portOptions(values.target_element_id)} onChange={(next) => set("target_port_id", next || null)}
            />
          )}
          <FolderField kind="connection" owner={{ projectId }} value={values.folder_id} onChange={(next) => set("folder_id", next)} />
          <FormGridFull>
            <TextAreaField helpNotNeeded label="Description" value={values.description} onChange={(value) => set("description", value)} />
          </FormGridFull>
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
