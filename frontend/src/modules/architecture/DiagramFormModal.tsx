/**
 * Module: modules/architecture/DiagramFormModal
 *
 * Create and edit dialog for a diagram, shared by the Diagrams list (create), the editor page (edit), the Links panel
 * (create) and told apart by whether `initial` is passed. A new diagram also takes quick links, tags, "Place the scope's
 * elements" and "Save and activate" (a diagram has no approval step). The scope is an element the diagram shows the inside
 * of; empty is the system context.
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
import type { ArchitectureDiagram, ArchitectureElement, DiagramFieldValues } from "./types";
import { isOutOfUse } from "./types";

/** What a new diagram takes beyond the shared fields. */
export interface DiagramCreateExtras {
  activate: boolean;
  populate: boolean;
  quickLinks: CollectedLink[];
  tags: string[];
}

/**
 * @param initial The diagram being edited; omit to create.
 * @param elements The elements that may be the scope (this project's own).
 * @param projectId The diagram's project, for quick links and tags.
 * @param defaultScopeId An element to preselect as the scope of a new diagram.
 * @param error A save error to show.
 * @param onSave Called with the values and, for a new diagram, the extras.
 */
export function DiagramFormModal({
  initial, elements, projectId, defaultScopeId = null, error, onCancel, onSave,
}: {
  initial?: ArchitectureDiagram;
  elements: ArchitectureElement[];
  projectId: string;
  defaultScopeId?: string | null;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: DiagramFieldValues, extras: DiagramCreateExtras) => void;
}) {
  const formatCode = useRecordCode();
  const [values, setValues] = useState<DiagramFieldValues>(() => (initial ? valuesFromDiagram(initial) : blankDiagramValues(defaultScopeId)));
  const [populate, setPopulate] = useState(false);
  const [quickLinks, setQuickLinks] = useState<CollectedLink[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const set = <K extends keyof DiagramFieldValues>(key: K, value: DiagramFieldValues[K]) =>
    setValues((prev) => ({ ...prev, [key]: value }));

  const scopeOptions = elements
    .filter((e) => !e.shared && (!isOutOfUse(e.status) || e.id === initial?.scope_element_id))
    .map((e) => ({ value: e.id, label: `${formatCode.code(e.unique_code, e.from_project_code)} ${e.name}` }));
  const valid = values.name.trim() !== "";

  function save(activate: boolean) {
    onSave({ ...values, name: values.name.trim() }, { activate, populate, quickLinks, tags });
  }

  return (
    <Modal title={initial ? `Edit ${initial.name}` : "New diagram"} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
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
          {!initial && (
            <FormGridFull>
              <div className="stack">
                <CheckboxField
                  label="Place the scope's elements" checked={populate} help={ARCHITECTURE_HELP.diagramPopulate} onChange={setPopulate}
                />
                <QuickLinkField projectId={projectId} artefactType="architecture_diagram" value={quickLinks} onChange={setQuickLinks} />
                <TagField projectId={projectId} artefactType="architecture_diagram" value={tags} onChange={setTags} />
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
