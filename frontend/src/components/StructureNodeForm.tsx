/**
 * Module: components/StructureNodeForm
 *
 * The one create and edit form for a component or a category, in a `SidePanel`: the name and the identifier prefix
 * (`NameAndPrefixFields`), Save in the panel header (`FormActions`).
 *
 * Responsibilities: create a component, create a category under a component, or edit either, through `StructureApi`;
 * show the server's refusal (a prefix already in use) in the panel and report success with a toast.
 *
 * Design decisions: create and edit share the field group, so a field added later reaches both. The prefix follows the
 * name on create only; an edit keeps the stored prefix.
 */
import { useState } from "react";

import type { NodeValues, StructureApi } from "../api/structure";
import type { Category, Component } from "../api/types";
import { useToast, toErrorMessage } from "../context/ToastContext";
import { useStrings } from "../context/TerminologyContext";
import { FormActions } from "./FormActions";
import { NameAndPrefixFields } from "./NameAndPrefixFields";
import { SidePanel } from "./SidePanel";

/** What the form creates or edits. */
export type StructureNodeTarget =
  | { kind: "component"; node?: Component }
  | { kind: "category"; component: Component; node?: Category };

/**
 * @param api The structure calls.
 * @param projectId The project.
 * @param target A component (create, or edit with `node`) or a category under `component` (create, or edit with `node`).
 * @param onSaved Called after a save so the page reloads the tree.
 * @param onClose Closes the panel.
 */
export function StructureNodeForm({
  api, projectId, target, onSaved, onClose,
}: {
  api: StructureApi;
  projectId: string;
  target: StructureNodeTarget;
  onSaved: () => void;
  onClose: () => void;
}) {
  const strings = useStrings();
  const { showToast } = useToast();
  const text = strings.structure;
  const editing = target.node;
  const [values, setValues] = useState<NodeValues>({ name: target.node?.name ?? "", prefix: target.node?.prefix ?? "" });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const valid = values.name.trim() !== "" && values.prefix.trim() !== "";
  const title = target.kind === "component"
    ? (editing ? text.editComponent(editing.name) : text.addComponent)
    : (editing ? text.editCategory(editing.name) : text.addCategory(target.component.name));

  async function save() {
    setSaving(true);
    setError(null);
    const body = { name: values.name.trim(), prefix: values.prefix.trim() };
    try {
      if (editing) await api.update(projectId, target.kind, editing.id, body);
      else if (target.kind === "component") await api.createComponent(projectId, body);
      else await api.createCategory(projectId, target.component.id, body);
      showToast(strings.mutation.success(`{${target.kind}}`, editing ? strings.mutation.past.update : strings.mutation.past.add));
      onSaved();
      onClose();
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
      setSaving(false);
    }
  }

  return (
    <SidePanel title={title} onClose={onClose}>
      <div className="stack">
        <NameAndPrefixFields
          api={api} projectId={projectId} kind={target.kind} followName={!editing}
          componentId={target.kind === "category" ? target.component.id : undefined} ignore={editing?.id}
          value={values} onChange={setValues}
        />
        <FormActions error={error} onCancel={onClose} onSave={() => void save()} saveDisabled={!valid || saving} />
      </div>
    </SidePanel>
  );
}
