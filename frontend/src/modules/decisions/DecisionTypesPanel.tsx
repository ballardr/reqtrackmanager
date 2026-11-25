/**
 * Module: modules/decisions/DecisionTypesPanel
 *
 * The project's Decision Type vocabulary: a plain, ordered, flat definition list, so it reuses `DefinitionList` as
 * `modules/compliance/ActionTypesPanel.tsx` does (style guide "one component per pattern"). Decision Types are
 * project-scoped like `ActionTypeDefinition`, including the nested-project fallback: `listDecisionTypes` returns the
 * effective, possibly inherited set and the panel displays it.
 *
 * It is a `projectAdminSections` entry, grouped with the project's other definition-table settings (Action Types,
 * Custom Fields). `render({projectId})` passes no parent state, so the panel fetches and reloads its own list, as
 * `DecisionTemplatesPanel.tsx` does.
 */
import { useState } from "react";

import { DefinitionList } from "../../components/DefinitionList";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as decisionsApi from "./api";
import type { DecisionTypeDefinition } from "./types";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";

export function DecisionTypesPanel({ projectId }: { projectId: string }) {
  const { showToast } = useToast();
  const [items, setItems] = useState<DecisionTypeDefinition[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  async function onReload() {
    try {
      setItems(await decisionsApi.listDecisionTypes(projectId));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "Could not load Decision Types."));
    }
  }

  useLoadOnChange(onReload, [projectId]);

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (items === null) return <Spinner />;

  return (
    <div className="stack">
      <p className="text-muted">
        The decision types available when creating a Decision in this project (e.g. Architecture, Design, Engineering,
        Strategy, Operational). A project with none of its own inherits its nearest parent project's, if it has one.
      </p>
      <DefinitionList<DecisionTypeDefinition>
        items={items}
        fields={[{ key: "name", getValue: (item) => item.name, placeholder: "Decision type name", ariaLabel: "Decision type name" }]}
        getReassignLabel={(item) => item.name}
        onMove={async (id, direction) => {
          await decisionsApi.moveDecisionType(projectId, id, direction);
          await onReload();
        }}
        onRename={async (id, values) => {
          await decisionsApi.renameDecisionType(projectId, id, values.name);
          await onReload();
        }}
        onAdd={async (values) => {
          await decisionsApi.createDecisionType(projectId, values.name);
          showToast("Decision type created.");
          await onReload();
        }}
        onDelete={async (id, reassignToId) => {
          await decisionsApi.deleteDecisionType(projectId, id, reassignToId);
          showToast("Decision type deleted.");
          await onReload();
        }}
        deleteLabel="Delete decision type"
        addLabel="Add decision type"
      />
    </div>
  );
}
