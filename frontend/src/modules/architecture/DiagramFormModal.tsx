/**
 * Module: modules/architecture/DiagramFormModal
 *
 * Create and edit dialog for a diagram, shared by the Diagrams list (create), the editor page (edit), the Links panel
 * (create) and told apart by whether `initial` is passed. A new diagram also takes quick links, tags, "Place the scope's
 * elements" and "Save and activate" (a diagram has no approval step). The scope is an element the diagram shows the inside
 * of; empty is the system context.
 *
 * Creating starts with a Type choice (Block diagram or State machine diagram, where both are offered): the type's own field
 * group follows (a block diagram's scope, folder and connection detail; a state machine diagram's element, through the
 * shared `StateMachineFields`), and the type is fixed once the diagram exists, so editing shows no Type. The quick links and
 * tags belong to the chosen type's record. A new state machine diagram has no states, so it cannot pass the checks that guard
 * activation; Save and activate is offered for a block diagram only, and a state machine diagram is activated from its
 * Change state menu once it is sound.
 */
import { useState } from "react";

import type { CollectedLink } from "../../api/artefactLinks";
import { FormActions } from "../../components/FormActions";
import { CheckboxField, TextAreaField, TextField } from "../../components/FormFields";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { QuickLinkField } from "../../components/QuickLinkField";
import { TagField } from "../../components/TagField";
import { useRecordCode } from "../../hooks/useRecordCode";
import { blankDiagramValues, valuesFromDiagram } from "./architectureFields";
import { FolderField } from "./FolderField";
import { ARCHITECTURE_HELP } from "./help";
import { StateMachineFields } from "./StateMachineFields";
import { blankStateMachineValues } from "./stateMachineFieldValues";
import type { ArchitectureDiagram, ArchitectureElement, DiagramFieldValues, DiagramKind, StateMachineFieldValues } from "./types";
import { DIAGRAM_KIND_LABEL, isOutOfUse } from "./types";

/** What a new diagram takes beyond the shared fields. */
export interface DiagramCreateExtras {
  /** The type chosen; the values of the other type are then not used. */
  kind: DiagramKind;
  /** The state machine diagram's fields (used when `kind` is `state_machine`). */
  stateMachine: StateMachineFieldValues;
  activate: boolean;
  populate: boolean;
  quickLinks: CollectedLink[];
  tags: string[];
}

/** Both diagram types, in the order the Type choice lists them. */
const ALL_KINDS: readonly DiagramKind[] = ["block", "state_machine"];

/** The registered artefact type of each diagram type, for the quick links and tags a new diagram takes. */
const ARTEFACT_TYPE: Record<DiagramKind, string> = { block: "architecture_diagram", state_machine: "architecture_state_machine_diagram" };

/**
 * @param initial The block diagram being edited; omit to create.
 * @param elements The elements that may be the scope (this project's own) or, for a state machine diagram, described.
 * @param projectId The diagram's project, for quick links and tags.
 * @param defaultScopeId An element to preselect as the scope of a new block diagram.
 * @param kinds The types a new diagram may be (both by default; the Links panel offers block diagrams only).
 * @param defaultKind The type preselected for a new diagram.
 * @param defaultElementId An element to preselect for a new state machine diagram.
 * @param error A save error to show.
 * @param onSave Called with the values and, for a new diagram, the extras.
 */
export function DiagramFormModal({
  initial, elements, projectId, defaultScopeId = null, kinds = ALL_KINDS, defaultKind = "block", defaultElementId = "", error, onCancel, onSave,
}: {
  initial?: ArchitectureDiagram;
  elements: ArchitectureElement[];
  projectId: string;
  defaultScopeId?: string | null;
  kinds?: readonly DiagramKind[];
  defaultKind?: DiagramKind;
  defaultElementId?: string;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: DiagramFieldValues, extras: DiagramCreateExtras) => void;
}) {
  const formatCode = useRecordCode();
  const [kind, setKind] = useState<DiagramKind>(kinds.includes(defaultKind) ? defaultKind : kinds[0]);
  const [values, setValues] = useState<DiagramFieldValues>(() => (initial ? valuesFromDiagram(initial) : blankDiagramValues(defaultScopeId)));
  const [stateMachine, setStateMachine] = useState<StateMachineFieldValues>(() => blankStateMachineValues(defaultElementId));
  const [populate, setPopulate] = useState(false);
  const [quickLinks, setQuickLinks] = useState<CollectedLink[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const set = <K extends keyof DiagramFieldValues>(key: K, value: DiagramFieldValues[K]) =>
    setValues((prev) => ({ ...prev, [key]: value }));

  const scopeOptions = elements
    .filter((e) => !e.shared && (!isOutOfUse(e.status) || e.id === initial?.scope_element_id))
    .map((e) => ({ value: e.id, label: `${formatCode.code(e.unique_code, e.from_project_code)} ${e.name}` }));
  const block = initial !== undefined || kind === "block";
  const valid = block ? values.name.trim() !== "" : stateMachine.name.trim() !== "" && stateMachine.element_id !== "";

  function save(activate: boolean) {
    onSave(
      { ...values, name: values.name.trim() },
      { kind, stateMachine: { ...stateMachine, name: stateMachine.name.trim() }, activate, populate, quickLinks, tags },
    );
  }

  return (
    <Modal title={initial ? `Edit ${initial.name}` : "New diagram"} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          {!initial && kinds.length > 1 && (
            <FormGridFull>
              <LabeledSelect
                help={ARCHITECTURE_HELP.diagramType} label="Type" value={kind} placeholder={null}
                options={kinds.map((k) => ({ value: k, label: DIAGRAM_KIND_LABEL[k] }))} onChange={(next) => setKind(next as DiagramKind)}
              />
            </FormGridFull>
          )}
          {block ? (
            <>
              <FormGridFull>
                <TextField helpNotNeeded required label="Name" value={values.name} onChange={(value) => set("name", value)} />
              </FormGridFull>
              <FormGridFull>
                <TextAreaField helpNotNeeded label="Purpose" value={values.purpose} onChange={(value) => set("purpose", value)} />
              </FormGridFull>
              <LabeledSelect
                help={ARCHITECTURE_HELP.diagramScope} label="Scope element" value={values.scope_element_id ?? ""}
                placeholder="System context (top-level elements)" options={scopeOptions}
                onChange={(next) => set("scope_element_id", next || null)}
              />
              <FolderField kind="diagram" owner={{ projectId }} value={values.folder_id} onChange={(next) => set("folder_id", next)} />
              <CheckboxField
                heading="Connections" label="Show connection detail" checked={values.connection_detail}
                help={ARCHITECTURE_HELP.diagramConnectionDetail} onChange={(checked) => set("connection_detail", checked)}
              />
            </>
          ) : (
            <StateMachineFields
              values={stateMachine} elements={elements}
              onChange={(key, value) => setStateMachine((prev) => ({ ...prev, [key]: value }))}
            />
          )}
          {!initial && (
            <FormGridFull>
              <div className="stack">
                {block && (
                  <CheckboxField
                    label="Place the scope's elements" checked={populate} help={ARCHITECTURE_HELP.diagramPopulate} onChange={setPopulate}
                  />
                )}
                <QuickLinkField projectId={projectId} artefactType={ARTEFACT_TYPE[kind]} value={quickLinks} onChange={setQuickLinks} />
                <TagField projectId={projectId} artefactType={ARTEFACT_TYPE[kind]} value={tags} onChange={setTags} />
              </div>
            </FormGridFull>
          )}
        </FormGrid>
        <FormActions
          error={error} onCancel={onCancel} onSave={() => save(false)} saveDisabled={!valid}
          onSaveAndActivate={initial || !block ? undefined : () => save(true)}
        />
      </div>
    </Modal>
  );
}
