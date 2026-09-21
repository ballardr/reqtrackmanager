/**
 * Module: modules/decisions/DecisionTypesPanel
 *
 * This project's Decision Type vocabulary (source overview §13/10.2) — a
 * plain, ordered, flat "definition" list, so this reuses `DefinitionList`
 * verbatim, the same way `modules/compliance/ActionTypesPanel.tsx` reuses it
 * for its own org-scoped action-type vocabulary (style guide "one component
 * per pattern" principle). Unlike that panel, Decision Types are
 * project-scoped (Phase 0 addendum item 5 — mirrors `ActionTypeDefinition`
 * exactly), so this lives inside `ProjectDecisionsPage.tsx`'s own "Decision
 * Types" tab rather than an org-admin page.
 */
import { DefinitionList } from "../../components/DefinitionList";
import { useToast } from "../../context/ToastContext";
import * as decisionsApi from "./api";
import type { DecisionTypeDefinition } from "./types";

export function DecisionTypesPanel({
  projectId,
  items,
  onReload,
}: {
  projectId: string;
  items: DecisionTypeDefinition[];
  onReload: () => Promise<void>;
}) {
  const { showToast } = useToast();

  return (
    <div className="stack">
      <p className="text-muted">
        The decision types available when creating a Decision in this project (e.g. Architecture, Design, Engineering,
        Strategy, Operational).
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
