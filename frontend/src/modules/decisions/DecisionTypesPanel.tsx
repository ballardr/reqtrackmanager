/**
 * Module: modules/decisions/DecisionTypesPanel
 *
 * This project's Decision Type vocabulary (source overview §13/10.2) — a
 * plain, ordered, flat "definition" list, so this reuses `DefinitionList`
 * verbatim, the same way `modules/compliance/ActionTypesPanel.tsx` reuses it
 * for its own org-scoped action-type vocabulary (style guide "one component
 * per pattern" principle). Decision Types are project-scoped (Phase 0
 * addendum item 5 — mirrors `ActionTypeDefinition` exactly, including its
 * nested-project inheritance fallback added in Phase 9, 2026-09-22 —
 * `listDecisionTypes` already returns the effective, possibly-inherited
 * set, so this panel just displays whatever the API gives it).
 *
 * Moved from a tab on `ProjectDecisionsPage.tsx` to Project Admin's own
 * `projectAdminSections` contribution in Phase 9 (2026-09-22) — grouped with
 * the project's other definition-table settings (Action Types, Custom
 * Fields) rather than the module's day-to-day working page, matching where
 * Action Types themselves already live. Since `render({projectId})` hands
 * this panel no parent-owned state (unlike the old tab, which shared
 * `ProjectDecisionsPage`'s own `decisionTypes` state), it now fetches and
 * reloads its own list — the same self-contained shape
 * `DecisionTemplatesPanel.tsx` already uses for org templates.
 */
import { useEffect, useState } from "react";

import { DefinitionList } from "../../components/DefinitionList";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as decisionsApi from "./api";
import type { DecisionTypeDefinition } from "./types";

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

  useEffect(() => {
    void onReload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

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
