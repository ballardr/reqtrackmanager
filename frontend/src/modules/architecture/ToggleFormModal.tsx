/**
 * Module: modules/architecture/ToggleFormModal
 *
 * Create and edit dialog for a diagram view switch: its name, whether it starts on, the rule that adds elements and
 * connections to it (element types, connection types, domains, tags) and the elements and connections chosen by hand. The
 * rule and the hand-picked members together decide what the switch hides when it is off. Saving stores the diagram's whole set
 * of switches, so the dialog returns one switch and the editor merges it.
 */
import { useState } from "react";

import { CheckboxField, TextField } from "../../components/FormFields";
import { FormActions } from "../../components/FormActions";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { Modal } from "../../components/Modal";
import { MultiSelectDropdown } from "../../components/MultiSelectDropdown";
import { TreeSelect } from "../../components/TreeSelect";
import { FieldCaption } from "../../components/FieldHelp";
import { useRecordCode } from "../../hooks/useRecordCode";
import { connectionTypeNodes } from "./connectionTypeTree";
import { ARCHITECTURE_HELP } from "./help";
import { blankToggle } from "./diagramToggles";
import {
  DOMAIN_LABEL, type ArchitectureConnection, type ArchitectureElement, type ConnectionType, type DiagramToggleValues, type Domain,
  type ElementType,
} from "./types";

const DOMAINS = Object.keys(DOMAIN_LABEL) as Domain[];

function toggled<T>(list: T[], item: T): T[] {
  return list.includes(item) ? list.filter((x) => x !== item) : [...list, item];
}

/**
 * @param initial The switch being edited; omit to create.
 * @param elements Elements that may be chosen by hand.
 * @param connections Connections that may be chosen by hand.
 * @param onSave Called with the switch to store.
 */
export function ToggleFormModal({
  initial, elementTypes, connectionTypes, elements, connections, onCancel, onSave,
}: {
  initial?: DiagramToggleValues;
  elementTypes: ElementType[];
  connectionTypes: ConnectionType[];
  elements: ArchitectureElement[];
  connections: ArchitectureConnection[];
  onCancel: () => void;
  onSave: (toggle: DiagramToggleValues) => void;
}) {
  const formatCode = useRecordCode();
  const [value, setValue] = useState<DiagramToggleValues>(initial ?? blankToggle());
  const [tagText, setTagText] = useState((initial?.rule.tags ?? []).join(", "));
  const rule = value.rule;
  const setRule = (patch: Partial<DiagramToggleValues["rule"]>) => setValue((v) => ({ ...v, rule: { ...v.rule, ...patch } }));

  function save() {
    const tags = tagText.split(",").map((t) => t.trim()).filter(Boolean);
    onSave({ ...value, name: value.name.trim(), rule: { ...value.rule, tags } });
  }

  return (
    <Modal title={initial ? `Edit switch ${initial.name}` : "New switch"} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <TextField help={ARCHITECTURE_HELP.toggleName} required label="Name" value={value.name} onChange={(name) => setValue((v) => ({ ...v, name }))} />
          <CheckboxField
            heading="State" label="On by default" checked={value.default_on} help={ARCHITECTURE_HELP.toggleDefault}
            onChange={(default_on) => setValue((v) => ({ ...v, default_on }))}
          />
          <FormGridFull>
            <FieldCaption label="Matched by rule" help={ARCHITECTURE_HELP.toggleRule} />
          </FormGridFull>
          <MultiSelectDropdown
            triggerLabel="Element types" emptyLabel="No element types"
            options={elementTypes.map((t) => ({
              value: t.id, label: t.name, checked: rule.element_type_ids.includes(t.id), optionLabel: `Match element type ${t.name}`,
              onToggle: () => setRule({ element_type_ids: toggled(rule.element_type_ids, t.id) }),
            }))}
          />
          <TreeSelect
            triggerLabel="Connection types" emptyLabel="No connection types" searchable
            nodes={connectionTypeNodes(connectionTypes)} selectedIds={rule.connection_type_ids}
            onChange={(next) => setRule({ connection_type_ids: next })}
          />
          <MultiSelectDropdown
            triggerLabel="Domains" emptyLabel="No domains"
            options={DOMAINS.map((d) => ({
              value: d, label: DOMAIN_LABEL[d], checked: rule.domains.includes(d), optionLabel: `Match domain ${DOMAIN_LABEL[d]}`,
              onToggle: () => setRule({ domains: toggled(rule.domains, d) }),
            }))}
          />
          <TextField helpNotNeeded label="Tags" value={tagText} onChange={setTagText} hint="Separate tags with commas" />
          <FormGridFull>
            <FieldCaption label="Chosen by hand" help={ARCHITECTURE_HELP.toggleMembers} />
          </FormGridFull>
          <MultiSelectDropdown
            triggerLabel="Elements" emptyLabel="No elements" filterable summaryLimit={2}
            options={elements.map((e) => ({
              value: e.id, label: `${formatCode.code(e.unique_code, e.from_project_code)} ${e.name}`, checked: value.element_ids.includes(e.id),
              optionLabel: `Include element ${e.name}`, onToggle: () => setValue((v) => ({ ...v, element_ids: toggled(v.element_ids, e.id) })),
            }))}
          />
          <MultiSelectDropdown
            triggerLabel="Connections" emptyLabel="No connections" filterable summaryLimit={2}
            options={connections.map((c) => ({
              value: c.id, label: `${formatCode.code(c.unique_code, c.from_project_code)} ${c.name || `${c.source_element_name} → ${c.target_element_name}`}`,
              checked: value.connection_ids.includes(c.id), optionLabel: `Include connection ${c.unique_code}`,
              onToggle: () => setValue((v) => ({ ...v, connection_ids: toggled(v.connection_ids, c.id) })),
            }))}
          />
        </FormGrid>
        <FormActions onCancel={onCancel} onSave={save} saveDisabled={value.name.trim() === ""} />
      </div>
    </Modal>
  );
}
