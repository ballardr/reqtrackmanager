/**
 * Module: modules/stakeholders/NeedListView
 *
 * The project's Stakeholder Need list: `RecordListView` configured with a Need's own columns. A need is
 * always project-scoped, so unlike the Persona and Stakeholder lists there is no organisation half, type or
 * scope column. Used by the People page for the Needs-only view; needs are created from its "New" menu, so
 * `onCreate` is optional here. Status renders through `NEED_STATUS_LABEL`.
 */
import { NeedFormModal } from "./NeedFormModal";
import type { TagFilterState } from "../../hooks/useTagFilter";
import type { ProjectScopeState } from "../../hooks/useProjectScope";
import { RecordListView } from "./RecordListView";
import type { Need, NeedFieldValues } from "./types";
import { NEED_STATUS_LABEL, NEED_STATUS_TONE } from "./types";

export function NeedListView({
  needs,
  ariaLabel,
  sectionKey,
  emptyText,
  includeArchived,
  onIncludeArchivedChange,
  onOpen,
  tagFilter,
  projectScope,
  onCreate,
}: {
  needs: Need[];
  ariaLabel: string;
  sectionKey: string;
  emptyText: string;
  includeArchived: boolean;
  onIncludeArchivedChange: (next: boolean) => void;
  onOpen: (need: Need) => void;
  /** The project's tag filter (state kept by the page); omit where tags are not offered. */
  tagFilter?: { projectId: string; filter: TagFilterState };
  /** The project page's list scope (state kept by the page); omit where related projects are not offered. */
  projectScope?: ProjectScopeState;
  /** Resolves on success; a rejection keeps the modal open and shows its message. Omit when needs are created elsewhere. */
  onCreate?: (values: NeedFieldValues) => Promise<void>;
}) {
  return (
    <RecordListView<Need, NeedFieldValues>
      records={needs}
      ariaLabel={ariaLabel}
      sectionKey={sectionKey}
      noun="Need"
      scopeLabel="project"
      emptyText={emptyText}
      showScope={false}
      statusLabel={NEED_STATUS_LABEL}
      statusTone={NEED_STATUS_TONE}
      searchText={(n) => `${n.unique_code} ${n.name} ${n.description}`}
      columnsBeforeType={[{ key: "need", label: "Need", render: (n) => n.description || "—" }]}
      columnsAfterScope={[]}
      includeArchived={includeArchived}
      onIncludeArchivedChange={onIncludeArchivedChange}
      onOpen={onOpen}
      tagFilter={tagFilter}
      projectScope={projectScope}
      onCreate={onCreate}
      renderCreateModal={
        onCreate ? (props) => <NeedFormModal error={props.error} onCancel={props.onCancel} onSave={props.onSave} /> : undefined
      }
    />
  );
}
