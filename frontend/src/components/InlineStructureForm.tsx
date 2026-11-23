/**
 * Module: components/InlineStructureForm
 *
 * The small form inside a create dialog for adding the first component, or the first category under a component,
 * when the project has none and a record cannot be created without one. It is the Structure page's field group
 * (`NameAndPrefixFields`, so the prefix is suggested the same way) with its own Add button. It creates the one node
 * through `StructureApi`, reports it, shows the server's refusal beside the button and changes nothing else.
 */
import { Plus } from "lucide-react";
import { useState } from "react";

import { structureApi, type NodeValues, type StructureApi, type StructureKind } from "../api/structure";
import { toErrorMessage } from "../context/ToastContext";
import { useStrings } from "../context/TerminologyContext";
import { NameAndPrefixFields } from "./NameAndPrefixFields";

/**
 * @param projectId The project.
 * @param kind Whether the first component or a first category is created.
 * @param componentId The component a category goes under (a category only).
 * @param onCreated Called after the node exists, so the caller reloads the tree.
 * @param api The structure calls (injectable for stories).
 */
export function InlineStructureForm({
  projectId, kind, componentId, onCreated, api = structureApi,
}: {
  projectId: string;
  kind: StructureKind;
  componentId?: string;
  onCreated: () => void | Promise<void>;
  api?: StructureApi;
}) {
  const strings = useStrings();
  const [values, setValues] = useState<NodeValues>({ name: "", prefix: "" });
  // Re-keyed after a create so the next node starts with the prefix following its name again.
  const [round, setRound] = useState(0);
  const [error, setError] = useState<string | null>(null);

  async function add() {
    setError(null);
    const body = { name: values.name.trim(), prefix: values.prefix.trim() };
    try {
      if (kind === "component") await api.createComponent(projectId, body);
      else if (componentId) await api.createCategory(projectId, componentId, body);
      setValues({ name: "", prefix: "" });
      setRound((n) => n + 1);
      await onCreated();
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
    }
  }

  return (
    <div className="stack">
      <NameAndPrefixFields
        key={round} api={api} projectId={projectId} kind={kind} componentId={componentId} followName
        value={values} onChange={setValues}
      />
      {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
      <div>
        <button type="button" className="btn btn-primary" onClick={() => void add()} disabled={!values.name.trim() || !values.prefix.trim()}>
          <Plus /> {kind === "component" ? strings.admin.newComponent : strings.admin.newCategory}
        </button>
      </div>
    </div>
  );
}
