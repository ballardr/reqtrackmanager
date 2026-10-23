/**
 * Module: modules/stakeholders/StakeholderListView
 *
 * The Stakeholder list shared by the project page (`ProjectStakeholdersPage`)
 * and the organisation panel (`OrgStakeholdersPanel`): `RecordListView`
 * configured with Stakeholder's own columns (Role, Cadence, Influence,
 * Interest), its create form and the "Add from org user" action. Influence and
 * Interest show the org's level *names* (`scheme`); they are plain labels, the
 * grid position itself is only computed server-side.
 *
 * Groups: `groups` adds a Groups column, a group filter (a group's
 * members include those in its descendants unless "Directly in the group only" is
 * ticked) and a "Group by" control. Grouping by a top-level group adds a column
 * named for it that shows each stakeholder's branch(es) under it and orders the
 * list by branch — the answer to a "custom column" for categorical data such as
 * Client. Filtering and ordering happen here, client-side, over the
 * `groups` each stakeholder already carries; the API offers the same via
 * `group_id` / `group_by`.
 *
 * `showLastEngaged` (project page only: an organisation list has no single
 * project's engagements) adds a "Last engaged" column from the date the API
 * derives from this project's engagements; "Never" when there is none.
 *
 * The project page's "Show hidden" filter and Visibility column are
 * `RecordListView`'s; the `includeHidden`/`onIncludeHiddenChange`/`onShowHidden`
 * props pass straight through.
 */
import { useMemo, useState } from "react";

import type { ScoringScheme } from "../../api/scoring";
import type { OrgUser } from "../../api/types";
import { toErrorMessage } from "../../context/ToastContext";
import { FilterBadge } from "../../components/FilterBadge";
import { FilterCheckbox } from "../../components/FilterPanel";
import { ScopedRecordCode } from "../../components/ScopedRecordCode";
import { branchNames, descendantIds, groupPath } from "./groupTree";
import type { TagFilterState } from "../../hooks/useTagFilter";
import type { ProjectScopeState } from "../../hooks/useProjectScope";
import { PeopleKindIcon } from "./PeopleKindIcon";
import { RecordListView, type RecordListPage } from "./RecordListView";
import { StakeholderFormModal } from "./StakeholderFormModal";
import { StakeholderGroupFilterFields } from "./StakeholderGroupFilterFields";
import { StakeholderFromUserModal } from "./StakeholderFromUserModal";
import type { CadenceHint, Stakeholder, StakeholderFieldValues, StakeholderGroup } from "./types";
import { STAKEHOLDER_SCOPE_LABEL, STAKEHOLDER_STATUS_LABEL, STAKEHOLDER_STATUS_TONE, TARGET_CADENCE_LABEL } from "./types";
import { levelName } from "./useStakeholderScheme";

export function StakeholderListView({
  stakeholders,
  ariaLabel,
  sectionKey,
  scopeLabel,
  emptyText,
  showScope,
  typeOptions,
  scheme,
  orgUsers,
  loadHint,
  groups = [],
  groupTier = "organization",
  showLastEngaged = false,
  includeArchived,
  onIncludeArchivedChange,
  includeHidden = false,
  onIncludeHiddenChange,
  onShowHidden,
  onOpen,
  tagFilter,
  projectScope,
  page,
  exportRecords,
  onCreate,
  onCreateFromUser,
}: {
  stakeholders: Stakeholder[];
  ariaLabel: string;
  sectionKey: string;
  /** "project" / "organisation", for the create modals' titles. */
  scopeLabel: string;
  emptyText: string;
  showScope: boolean;
  typeOptions: { value: string; label: string }[];
  scheme: ScoringScheme | null;
  orgUsers: OrgUser[];
  loadHint: (influenceLevelId: string, interestLevelId: string) => Promise<CadenceHint>;
  /** Every Stakeholder group this view can see, flat; omit to leave the group controls out. */
  groups?: StakeholderGroup[];
  /** Which tier of `groups` a new stakeholder can be put into from here. */
  groupTier?: "organization" | "project";
  /** Adds the "Last engaged" column (project page only). */
  showLastEngaged?: boolean;
  includeArchived: boolean;
  onIncludeArchivedChange: (next: boolean) => void;
  includeHidden?: boolean;
  /** Offered on the project page only; omit where there is nothing to hide. */
  onIncludeHiddenChange?: (next: boolean) => void;
  /** Re-shows a hidden stakeholder in this project (the Visibility cell's "Show" action). */
  onShowHidden?: (stakeholder: Stakeholder) => void;
  onOpen: (stakeholder: Stakeholder) => void;
  /** The project's tag filter (state kept by the page); omit where tags are not offered. */
  tagFilter?: { projectId: string; filter: TagFilterState };
  /** The project page's list scope (state kept by the page); omit where related projects are not offered. */
  projectScope?: ProjectScopeState;
  /** The page header (title, actions, tabs) this list owns when it is a whole page. */
  page?: RecordListPage;
  /** Offers the shared Export and Import of Stakeholders on a list page, or beside an organisation panel's New button: the project or organisation, and what to do after an import. */
  exportRecords?: { projectId?: string; organizationId?: string; onImported?: () => void };
  /** Resolves on success; a rejection keeps the modal open and shows its message. `groupIds` are the groups chosen on the form. Omit when stakeholders are created elsewhere. */
  onCreate?: (values: StakeholderFieldValues, groupIds: string[]) => Promise<void>;
  /** Same contract, for the "Add from org user" modal; omit to leave that button out. */
  onCreateFromUser?: (values: { user_id: string; stakeholder_type_id: string | null; role: string; activate?: boolean }) => Promise<void>;
}) {
  const [fromUserOpen, setFromUserOpen] = useState(false);
  const [fromUserError, setFromUserError] = useState<string | null>(null);
  const [groupFilter, setGroupFilter] = useState("");
  const [directOnly, setDirectOnly] = useState(false);
  const [groupBy, setGroupBy] = useState("");

  const groupByRoot = groups.find((g) => g.id === groupBy);

  const visible = useMemo(() => {
    let rows = stakeholders;
    if (groupFilter) {
      const wanted = new Set([groupFilter, ...(directOnly ? [] : descendantIds(groups, groupFilter))]);
      rows = rows.filter((s) => s.groups.some((g) => wanted.has(g.id)));
    }
    if (groupBy) {
      const key = (s: Stakeholder) => branchNames(groups, s.groups, groupBy)[0] ?? "\uffff";
      rows = [...rows].sort((a, b) => key(a).localeCompare(key(b)));
    }
    return rows;
  }, [stakeholders, groups, groupFilter, directOnly, groupBy]);

  return (
    <>
      <RecordListView<Stakeholder, StakeholderFieldValues & { group_ids?: string[] }>
        records={visible}
        exportRecords={exportRecords && {
          ...exportRecords, recordType: "stakeholder",
          extraParams: { ...(groupFilter ? { group_id: groupFilter } : {}), ...(groupFilter && directOnly ? { direct_only: "true" } : {}) },
        }}
        ariaLabel={ariaLabel}
        sectionKey={sectionKey}
        noun="Stakeholder"
        scopeLabel={scopeLabel}
        emptyText={emptyText}
        showScope={showScope}
        statusLabel={STAKEHOLDER_STATUS_LABEL}
        statusTone={STAKEHOLDER_STATUS_TONE}
        scopeLabels={STAKEHOLDER_SCOPE_LABEL}
        typeName={(s) => s.stakeholder_type_name}
        nameIcon={() => <PeopleKindIcon kind="stakeholder" />}
        searchText={(s) => `${s.unique_code} ${s.name} ${s.role} ${s.organisation_group}`}
        columnsBeforeType={[{ key: "role", label: "Role", render: (s) => s.role || "—" }]}
        columnsAfterScope={[
          { key: "cadence", label: "Cadence", render: (s) => (s.target_cadence ? TARGET_CADENCE_LABEL[s.target_cadence] : "—") },
          ...(showLastEngaged
            ? [{ key: "last-engaged", label: "Last engaged", render: (s: Stakeholder) => s.last_engaged ?? "Never" }]
            : []),
          { key: "influence", label: "Influence", render: (s) => levelName(scheme, "influence", s.influence_level_id) },
          { key: "interest", label: "Interest", render: (s) => levelName(scheme, "interest", s.interest_level_id) },
          ...(groups.length > 0
            ? [{
                key: "groups", label: "Groups",
                render: (s: Stakeholder) =>
                  s.groups.length === 0 ? "—" : (
                    <span className="row" style={{ gap: "var(--space-1)" }}>
                      {s.groups.map((g) => (
                        <FilterBadge key={g.id} active={groupFilter === g.id} onClick={() => setGroupFilter(groupFilter === g.id ? "" : g.id)}>
                          <span title={groupPath(groups, g.id)}>
                            {g.name}{" "}
                            <span className="text-muted">
                              <ScopedRecordCode record={g} />
                            </span>
                          </span>
                        </FilterBadge>
                      ))}
                    </span>
                  ),
              }]
            : []),
          ...(groupByRoot
            ? [{
                key: "group-by", label: groupByRoot.name,
                render: (s: Stakeholder) => branchNames(groups, s.groups, groupByRoot.id).join(", ") || "—",
              }]
            : []),
        ]}
        extraFilters={
          <StakeholderGroupFilterFields
            groups={groups}
            groupId={groupFilter}
            onGroupIdChange={setGroupFilter}
            groupBy={groupBy}
            onGroupByChange={setGroupBy}
            afterGroup={groupFilter && <FilterCheckbox label="Directly in the group only" checked={directOnly} onChange={setDirectOnly} />}
          />
        }
        toolbar={
          onCreateFromUser && (
            <button className="btn" onClick={() => setFromUserOpen(true)}>
              Add from org user
            </button>
          )
        }
        includeArchived={includeArchived}
        onIncludeArchivedChange={onIncludeArchivedChange}
        includeHidden={includeHidden}
        onIncludeHiddenChange={onIncludeHiddenChange}
        onShowHidden={onShowHidden}
        onOpen={onOpen}
      tagFilter={tagFilter}
      projectScope={projectScope}
      page={page}
        onCreate={onCreate && (({ group_ids: groupIds = [], ...values }) => onCreate(values as StakeholderFieldValues, groupIds))}
        renderCreateModal={onCreate ? (props) => (
          <StakeholderFormModal
            {...props} typeOptions={typeOptions} scheme={scheme} loadHint={loadHint}
            groups={groups} groupTier={groupTier}
          />
        ) : undefined}
      />
      {fromUserOpen && onCreateFromUser && (
        <StakeholderFromUserModal
          scopeLabel={scopeLabel}
          orgUsers={orgUsers}
          typeOptions={typeOptions}
          error={fromUserError}
          onCancel={() => { setFromUserOpen(false); setFromUserError(null); }}
          onSave={async (values) => {
            setFromUserError(null);
            try {
              await onCreateFromUser(values);
              setFromUserOpen(false);
            } catch (err) {
              setFromUserError(toErrorMessage(err, "Could not create the Stakeholder."));
            }
          }}
        />
      )}
    </>
  );
}
