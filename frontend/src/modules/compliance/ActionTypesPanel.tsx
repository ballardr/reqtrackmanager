/**
 * Module: modules/compliance/ActionTypesPanel
 *
 * The organisation-scoped required-action-type vocabulary (§6) — a plain,
 * ordered, flat "definition" list, so this reuses `DefinitionList` verbatim
 * (the same shared rename/reorder/add/delete-with-reassign component
 * `OrgAdminPage.tsx` already uses for project statuses and link types)
 * rather than reimplementing that logic a third time, per the style guide's
 * "one component per pattern" principle.
 *
 * `items`/`onReload` are owned by `ComplianceAdminPanel` (not fetched here)
 * — the same list is also needed by `RequirementTree`'s required-action
 * editor on the Standards tab, and owning a second, independent copy here
 * would let the two tabs drift out of sync with each other after a rename/
 * add/delete until an unrelated remount happened to refetch both.
 */
import { DefinitionList } from "../../components/DefinitionList";
import { useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import type { ComplianceActionType } from "./types";

export function ActionTypesPanel({
  orgId,
  items,
  onReload,
}: {
  orgId: string;
  items: ComplianceActionType[];
  onReload: () => Promise<void>;
}) {
  const { showToast } = useToast();

  return (
    <div className="stack">
      <p className="text-muted">
        The required-action types available when defining a required action on a compliance requirement (§6).
      </p>
      <DefinitionList<ComplianceActionType>
        items={items}
        fields={[{ key: "name", getValue: (item) => item.name, placeholder: "Action type name", ariaLabel: "Action type name" }]}
        getReassignLabel={(item) => item.name}
        onMove={async (id, direction) => {
          await complianceApi.moveActionType(orgId, id, direction);
          await onReload();
        }}
        onRename={async (id, values) => {
          await complianceApi.renameActionType(orgId, id, values.name);
          await onReload();
        }}
        onAdd={async (values) => {
          await complianceApi.createActionType(orgId, values.name);
          showToast("Action type created.");
          await onReload();
        }}
        onDelete={async (id, reassignToId) => {
          await complianceApi.deleteActionType(orgId, id, reassignToId);
          showToast("Action type deleted.");
          await onReload();
        }}
        deleteLabel="Delete action type"
        addLabel="Add action type"
      />
    </div>
  );
}
