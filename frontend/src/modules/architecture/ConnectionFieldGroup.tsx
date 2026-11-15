/**
 * Module: modules/architecture/ConnectionFieldGroup
 *
 * The fields of a connection that the create dialog, the edit dialog and the diagram's Selection card all take (name, the guided
 * type picker, protocol, the two ends with their ports, folder, description), as one group so a field added later reaches every
 * place. The caller owns the values and the draft; the group holds only the picker's "Show all types" switch.
 *
 * The type picker is guided, never restrictive (`connectionGuidance`): it lists the types whose domain fits both ends, with the
 * types suggested for the ends' element types first, offers every type on "Show all types", and warns when a type that does not
 * fit is chosen.
 */
import { useState } from "react";

import { TextAreaField, TextField, ToggleField } from "../../components/FormFields";
import { FormGridFull } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import { TreeSelectField } from "../../components/TreeSelectField";
import { useRecordCode } from "../../hooks/useRecordCode";
import { guideConnectionTypes, mismatchWarning, suggestedGroup } from "./connectionGuidance";
import { connectionTypeNodes } from "./connectionTypeTree";
import { FolderField } from "./FolderField";
import { ARCHITECTURE_HELP } from "./help";
import type { ArchitectureConnection, ArchitectureElement, ConnectionFieldValues, ConnectionType, ElementType } from "./types";
import { isOutOfUse } from "./types";

/**
 * @param values The current values; `connection_type_id` is the type shown as chosen.
 * @param onChange Called with one changed field.
 * @param connectionTypes The types that may be chosen.
 * @param elementTypes The project's element types, which give each end's domain and suggested connection types; with none the
 *   picker offers every connection type.
 * @param elements Every element either end may be (the project's own and those shared with it).
 * @param projectId The connection's project, for the folder choice.
 * @param saved The connection being edited, so an end that is now out of use stays selectable.
 * @param autoFocusName True to put the cursor in the name when the group first appears (a connection just added to a diagram).
 */
export function ConnectionFieldGroup({
  values, onChange, connectionTypes, elementTypes, elements, projectId, saved, autoFocusName = false,
}: {
  values: ConnectionFieldValues;
  onChange: <K extends keyof ConnectionFieldValues>(key: K, value: ConnectionFieldValues[K]) => void;
  connectionTypes: ConnectionType[];
  elementTypes: ElementType[];
  elements: ArchitectureElement[];
  projectId: string;
  saved?: ArchitectureConnection;
  autoFocusName?: boolean;
}) {
  const formatCode = useRecordCode();
  const [showAll, setShowAll] = useState(false);

  const options = elements.filter((e) => !isOutOfUse(e.status) || e.id === saved?.source_element_id || e.id === saved?.target_element_id);
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
  const typeId = values.connection_type_id;
  const chosen = connectionTypes.find((t) => t.id === typeId);
  // A chosen type stays in the list even when the domain filter would hide it, so the picker never loses the choice.
  const stillHidden = guidance.hidden.filter((t) => t.id !== typeId);
  const listed = showAll || stillHidden.length === 0
    ? connectionTypes
    : connectionTypes.filter((t) => guidance.offered.includes(t) || t.id === typeId);
  const typeNodes = [...suggestedGroup(guidance.suggested), ...connectionTypeNodes(listed)];
  const warning = mismatchWarning(chosen, ends);

  return (
    <>
      <FormGridFull>
        <TextField
          helpNotNeeded label="Name" value={values.name} onChange={(value) => onChange("name", value)}
          inputProps={autoFocusName ? { autoFocus: true, onFocus: (event) => event.currentTarget.select() } : undefined}
        />
      </FormGridFull>
      <div className="stack">
        <TreeSelectField
          help={ARCHITECTURE_HELP.connectionType} required single searchable label="Connection type"
          value={typeId ? [typeId] : []} emptyLabel="Choose a type"
          nodes={typeNodes} onChange={([next]) => onChange("connection_type_id", next ?? "")}
        />
        {(showAll || stillHidden.length > 0) && (
          <ToggleField
            help={ARCHITECTURE_HELP.connectionTypeShowAll} label="Show all types" checked={showAll}
            onChange={setShowAll} hint={showAll ? undefined : `${stillHidden.length} hidden`}
          />
        )}
        {warning && <p role="status" style={{ margin: 0, color: "var(--color-warning)" }}>{warning}</p>}
      </div>
      <TextField help={ARCHITECTURE_HELP.connectionProtocol} label="Protocol" value={values.protocol} onChange={(value) => onChange("protocol", value)} />
      <LabeledSelect
        help={ARCHITECTURE_HELP.connectionSource} required label="Source element" value={values.source_element_id}
        placeholder="Choose an element" options={elementOptions}
        onChange={(next) => { onChange("source_element_id", next); onChange("source_port_id", null); }}
      />
      {portOptions(values.source_element_id).length > 0 && (
        <LabeledSelect
          help={ARCHITECTURE_HELP.connectionPort} label="Source port" value={values.source_port_id ?? ""} placeholder="No port"
          options={portOptions(values.source_element_id)} onChange={(next) => onChange("source_port_id", next || null)}
        />
      )}
      <LabeledSelect
        help={ARCHITECTURE_HELP.connectionTarget} required label="Target element" value={values.target_element_id}
        placeholder="Choose an element" options={elementOptions}
        onChange={(next) => { onChange("target_element_id", next); onChange("target_port_id", null); }}
      />
      {portOptions(values.target_element_id).length > 0 && (
        <LabeledSelect
          help={ARCHITECTURE_HELP.connectionPort} label="Target port" value={values.target_port_id ?? ""} placeholder="No port"
          options={portOptions(values.target_element_id)} onChange={(next) => onChange("target_port_id", next || null)}
        />
      )}
      <FolderField kind="connection" owner={{ projectId }} value={values.folder_id} onChange={(next) => onChange("folder_id", next)} />
      <FormGridFull>
        <TextAreaField helpNotNeeded label="Description" value={values.description} onChange={(value) => onChange("description", value)} />
      </FormGridFull>
    </>
  );
}
