/**
 * Module: modules/stakeholders/PeopleListView
 *
 * The combined list on the People page: Personas, Stakeholders and Groups as rows of one table, for
 * when more than one kind is selected. It is `RecordListView` (the shell every list in this module uses)
 * with the columns the kinds share — Name (with the kind's icon), Code, Kind, Details (a role or short description), Type, Scope,
 * Status — and no create form: records are created from the page's New menu. A kind's own columns and
 * filters (Stakeholders' influence and groups, Personas' weight) live in that kind's list, which the page
 * shows when just that kind is selected. Kind, status and scope render through their label maps.
 */
import { Badge } from "../../components/Badge";
import { PeopleKindIcon } from "./PeopleKindIcon";
import { PEOPLE_KIND_LABEL, type PeopleRow } from "./peopleRows";
import type { TagFilterState } from "../../hooks/useTagFilter";
import type { ProjectScopeState } from "../../hooks/useProjectScope";
import { RecordListView, type ExportRecords, type RecordListPage } from "./RecordListView";
import { PERSONA_SCOPE_LABEL, PERSONA_STATUS_LABEL, PERSONA_STATUS_TONE } from "./types";

export function PeopleListView({
  rows,
  includeArchived,
  onIncludeArchivedChange,
  includeHidden,
  onIncludeHiddenChange,
  onShowHidden,
  onOpen,
  tagFilter,
  projectScope,
  page,
  exportRecords,
}: {
  rows: PeopleRow[];
  includeArchived: boolean;
  onIncludeArchivedChange: (next: boolean) => void;
  includeHidden: boolean;
  onIncludeHiddenChange?: (next: boolean) => void;
  /** Re-shows a hidden Persona or Stakeholder in this project (the Visibility cell's "Show" action). */
  onShowHidden?: (row: PeopleRow) => void;
  onOpen: (row: PeopleRow) => void;
  /** The project's tag filter (state kept by the page); omit where tags are not offered. */
  tagFilter?: { projectId: string; filter: TagFilterState };
  /** The project page's list scope (state kept by the page); omit where related projects are not offered. */
  projectScope?: ProjectScopeState;
  /** The page header (title, actions, tabs) this list owns when it is a whole page. */
  page?: RecordListPage;
  /** The kinds listed, each offered its own Export and Import on a list page. */
  exportRecords?: ExportRecords[];
}) {
  return (
    <RecordListView<PeopleRow, never>
      records={rows}
      ariaLabel="People"
      sectionKey="stakeholders.people.list"
      noun="Person"
      scopeLabel="project"
      emptyText="Nothing recorded for this project yet."
      showScope
      // Personas, Stakeholders and Needs share one lifecycle (draft, active, retired), so one map serves them all.
      statusLabel={PERSONA_STATUS_LABEL}
      statusTone={PERSONA_STATUS_TONE}
      scopeLabels={PERSONA_SCOPE_LABEL}
      typeName={(r) => r.typeName}
      nameIcon={(r) => <PeopleKindIcon kind={r.kind} />}
      searchText={(r) => `${r.unique_code} ${r.name} ${r.summary} ${PEOPLE_KIND_LABEL[r.kind]}`}
      columnsBeforeType={[
        { key: "kind", label: "Kind", render: (r) => <Badge>{PEOPLE_KIND_LABEL[r.kind]}</Badge> },
        { key: "summary", label: "Details", render: (r) => r.summary || "—" },
      ]}
      columnsAfterScope={[]}
      includeArchived={includeArchived}
      onIncludeArchivedChange={onIncludeArchivedChange}
      includeHidden={includeHidden}
      onIncludeHiddenChange={onIncludeHiddenChange}
      onShowHidden={onShowHidden}
      onOpen={onOpen}
      tagFilter={tagFilter}
      projectScope={projectScope}
      page={page}
      exportRecords={exportRecords}
    />
  );
}
