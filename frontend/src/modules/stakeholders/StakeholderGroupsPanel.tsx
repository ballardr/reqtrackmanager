/**
 * Module: modules/stakeholders/StakeholderGroupsPanel
 *
 * The Stakeholder group manager: the group tree with create, rename,
 * move, reorder, "one branch per stakeholder" and delete, the selected group's
 * members, and the "create groups from Organisation / group text" action. One
 * component serves both tiers — the organisation overview (`organizationId`) and
 * a project (`projectId`) — because the tree, rules and controls are identical;
 * only the API and which groups are editable differ.
 *
 * Layout: the groups are the shared `FolderTreeList` grid (Name, Code, Members, Scope, Rule and a row actions menu), so
 * every column lines up whatever the names hold, and the selected group's members are a `DirectoryTable` under it.
 * A group with child groups is a folder row (its name opens and closes it) and a group without is an item row (its name
 * selects it); the Members count selects either, and the selected row is outlined. The folders a person collapsed are
 * remembered per list (`useOpenFolders`); every folder starts open.
 *
 * In a project the tree also shows the organisation's groups, marked
 * "Organisation" and read-only (they are edited from the organisation view; their Export is on the People page); a
 * project group can be created under one. Deleting is a tier-1 `ConfirmDialog`
 * that states the member and child counts, since it removes memberships and
 * moves child groups up but never deletes a stakeholder. Every mutating control
 * always renders; the backend enforces the Stakeholder manage permission and a
 * 403 surfaces as a toast. The organisation view also offers the shared Export and Import of its own groups.
 */
import { Users } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { CollectedLink } from "../../api/artefactLinks";
import { ActionMenu, type ActionMenuItem } from "../../components/ActionMenu";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FolderTreeList, type FolderTreeColumn } from "../../components/FolderTreeList";
import { ListActions } from "../../components/ListActions";
import { LabeledSelect } from "../../components/LabeledSelect";
import { ScopedRecordCode } from "../../components/ScopedRecordCode";
import { Spinner } from "../../components/Spinner";
import { cycleSort } from "../../components/sortState";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useCommitQuickLinks } from "../../hooks/useCommitQuickLinks";
import { useCommitTags } from "../../hooks/useCommitTags";
import { useOpenFolders } from "../../hooks/useOpenFolders";
import { useUrlSort } from "../../hooks/useUrlFilter";
import type { FolderNode } from "../../utils/reportFolders";
import { orgStakeholderApi, orgStakeholderGroupApi, projectStakeholderApi, projectStakeholderGroupApi } from "./api";
import { type GroupNode, ancestorsOf, buildGroupTree, groupFolderNodes, parentGroupIds } from "./groupTree";
import { GroupsFromTextModal } from "./GroupsFromTextModal";
import { StakeholderGroupFormModal } from "./StakeholderGroupFormModal";
import type {
  GroupTextProposal, StakeholderGroup, StakeholderGroupFieldValues, StakeholderGroupMember,
} from "./types";
import { STAKEHOLDER_SCOPE_LABEL } from "./types";
import { Badge } from "../../components/Badge";
import { MarkdownView } from "../../components/MarkdownView";

const MEMBER_SORT_KEYS = ["name"] as const;

type FormState = { initial?: StakeholderGroup; parentId?: string | null } | null;

export function StakeholderGroupsPanel({
  organizationId,
  projectId,
  initialGroupId,
}: {
  /** Set for the organisation overview. */
  organizationId?: string;
  /** Set for a project. */
  projectId?: string;
  /** A group to open selected (deep link from a relationship). */
  initialGroupId?: string | null;
}) {
  const { showToast } = useToast();
  const tier = projectId ? "project" : "organization";
  const scopeId = (projectId ?? organizationId) as string;
  const groupApi = projectId ? projectStakeholderGroupApi : orgStakeholderGroupApi;
  const commitQuickLinks = useCommitQuickLinks(projectId ?? "", "stakeholder_group");
  const commitTags = useCommitTags(projectId ?? "", "stakeholder_group");
  const stakeholderApi = projectId ? projectStakeholderApi : orgStakeholderApi;

  const [groups, setGroups] = useState<StakeholderGroup[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(initialGroupId ?? null);
  const [members, setMembers] = useState<StakeholderGroupMember[] | null>(null);
  const [candidates, setCandidates] = useState<{ value: string; label: string }[]>([]);
  const [picked, setPicked] = useState("");
  const [form, setForm] = useState<FormState>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<StakeholderGroup | null>(null);
  const [proposals, setProposals] = useState<GroupTextProposal[] | null>(null);
  const [proposalError, setProposalError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const reload = useCallback(() => setRefresh((n) => n + 1), []);
  // The hook keeps a set of ids per list; here it holds the collapsed groups, so a new group under a parent is visible.
  const [collapsed, setCollapsed] = useOpenFolders(`stakeholder-groups-collapsed-${tier}-${scopeId}`);
  const [memberSort, setMemberSort] = useUrlSort(MEMBER_SORT_KEYS);
  const opened = useRef(false);

  useEffect(() => {
    let active = true;
    groupApi
      .list(scopeId)
      .then((list) => {
        if (!active) return;
        setGroups(list);
        setLoadError(null);
      })
      .catch((err) => {
        if (active) setLoadError(toErrorMessage(err, "The Stakeholders & Personas module is not enabled here, or you do not have access to it."));
      });
    return () => {
      active = false;
    };
  }, [groupApi, scopeId, refresh]);

  useEffect(() => {
    if (!selectedId) return;
    let active = true;
    groupApi.listMembers(scopeId, selectedId).then((rows) => active && setMembers(rows)).catch(() => active && setMembers([]));
    return () => {
      active = false;
    };
  }, [groupApi, scopeId, selectedId, refresh]);

  useEffect(() => {
    stakeholderApi
      .list(scopeId)
      .then((list) => setCandidates(list.map((s) => ({ value: s.id, label: s.name }))))
      .catch(() => setCandidates([]));
  }, [stakeholderApi, scopeId]);

  const tree = useMemo(() => buildGroupTree(groups ?? []), [groups]);
  const nodes = useMemo(() => groupFolderNodes(tree), [tree]);
  const expanded = useMemo(() => new Set(parentGroupIds(tree).filter((id) => !collapsed.has(id))), [tree, collapsed]);
  // A group's siblings of its own tier, in order: Move up and Move down act among them.
  const siblingsById = useMemo(() => {
    const found = new Map<string, GroupNode[]>();
    const visit = (level: GroupNode[]) => {
      for (const n of level) {
        found.set(n.id, level.filter((g) => g.scope === n.scope));
        visit(n.children);
      }
    };
    visit(tree);
    return found;
  }, [tree]);
  const selected = groups?.find((g) => g.id === selectedId) ?? null;
  const editable = (g: StakeholderGroup) => g.scope === tier;

  // A group opened from a link is shown, so the folders above it are opened once the list has loaded.
  useEffect(() => {
    if (opened.current || !groups || !initialGroupId) return;
    opened.current = true;
    for (const parent of ancestorsOf(groups, initialGroupId)) setCollapsed(parent.id, false);
  }, [groups, initialGroupId, setCollapsed]);

  async function act(action: () => Promise<unknown>, success: string, failure: string): Promise<boolean> {
    try {
      await action();
      showToast(success);
      reload();
      return true;
    } catch (err) {
      showToast(toErrorMessage(err, failure), "error");
      return false;
    }
  }

  async function saveForm(values: StakeholderGroupFieldValues, quickLinks: CollectedLink[], tags: string[]) {
    setFormError(null);
    try {
      let createdId: string | null = null;
      if (form?.initial) await groupApi.update(scopeId, form.initial.id, values);
      else createdId = (await groupApi.create(scopeId, values)).id;
      showToast(form?.initial ? "Group updated." : "Group created.");
      setForm(null);
      if (values.parent_group_id) setCollapsed(values.parent_group_id, false);
      if (createdId && projectId) {
        await commitQuickLinks(createdId, quickLinks);
        await commitTags(createdId, tags);
      }
      reload();
    } catch (err) {
      setFormError(toErrorMessage(err, "Could not save this group."));
    }
  }

  async function openProposals() {
    try {
      setProposalError(null);
      setProposals(await groupApi.textProposals(scopeId));
    } catch (err) {
      showToast(toErrorMessage(err, "Could not read the Organisation / group values."), "error");
    }
  }

  async function confirmProposals(names: string[]) {
    try {
      const result = await groupApi.createFromText(scopeId, names);
      showToast(`Created ${result.group_ids.length} ${result.group_ids.length === 1 ? "group" : "groups"}, ${result.memberships_added} added.`);
      setProposals(null);
      reload();
    } catch (err) {
      setProposalError(toErrorMessage(err, "Could not create the groups."));
    }
  }

  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (groups === null) return <Spinner />;

  const memberIds = new Set((members ?? []).map((m) => m.stakeholder_id));
  const shownMembers = [...(members ?? [])].sort((a, b) =>
    memberSort?.direction === "desc" ? b.name.localeCompare(a.name) : a.name.localeCompare(b.name),
  );

  const membersButton = (group: GroupNode) => (
    <button
      type="button" className="btn btn-sm" aria-label={`Show members of ${group.name}`} title={`Show members of ${group.name}`}
      aria-pressed={group.id === selectedId} onClick={() => setSelectedId(group.id)}
    >
      {group.member_count}
    </button>
  );
  const scopeBadge = (g: GroupNode) => (g.scope !== tier ? <Badge>{STAKEHOLDER_SCOPE_LABEL[g.scope]}</Badge> : null);
  const ruleBadge = (g: GroupNode) =>
    g.exclusive_children ? <Badge title="A stakeholder can be in only one child group.">One branch</Badge> : null;

  // A folder row carries its group as `item`, so one renderer serves folders and items.
  const columns: FolderTreeColumn<GroupNode>[] = [
    {
      id: "code", header: "Code", width: "minmax(8rem, 12rem)",
      render: (g) => <ScopedRecordCode record={g} />,
      renderFolder: (node) => (node.item ? <ScopedRecordCode record={node.item} /> : null),
    },
    {
      id: "members", header: "Members", width: "minmax(5rem, 7rem)",
      render: membersButton,
      renderFolder: (node) => (node.item ? membersButton(node.item) : null),
    },
    ...(projectId
      ? [{
        id: "scope", header: "Scope", width: "minmax(6rem, 9rem)", hideBelow: true,
        render: scopeBadge,
        renderFolder: (node: FolderNode<GroupNode>) => (node.item ? scopeBadge(node.item) : null),
      }]
      : []),
    {
      id: "rule", header: "Rule", width: "minmax(6rem, 9rem)", hideBelow: true,
      render: ruleBadge,
      renderFolder: (node) => (node.item ? ruleBadge(node.item) : null),
    },
  ];

  /** The row's actions menu; a group of the other tier (the organisation's, in a project) has none. */
  function actionsFor(group: GroupNode) {
    return editable(group) ? <ActionMenu triggerLabel={`Actions for ${group.name}`} items={menuFor(group)} /> : null;
  }

  function menuFor(group: GroupNode): ActionMenuItem[] {
    const siblings = siblingsById.get(group.id) ?? [];
    const index = siblings.findIndex((g) => g.id === group.id);
    const moveFailed = "Could not move this group.";
    return [
      { label: "Edit", onSelect: () => { setFormError(null); setForm({ initial: group }); } },
      { label: `Add group under ${group.name}`, onSelect: () => { setFormError(null); setForm({ parentId: group.id }); } },
      { label: "Move up", disabled: index <= 0, onSelect: () => void act(() => groupApi.move(scopeId, group.id, "up"), "Group moved.", moveFailed) },
      { label: "Move down", disabled: index === siblings.length - 1, onSelect: () => void act(() => groupApi.move(scopeId, group.id, "down"), "Group moved.", moveFailed) },
      { label: "Delete", danger: true, onSelect: () => setDeleting(group) },
    ];
  }

  const memberColumns: DirectoryColumn<StakeholderGroupMember>[] = [
    { key: "name", label: "Name", sortable: true, render: (m) => m.name },
    { key: "membership", label: "Membership", render: (m) => (m.direct ? "Direct" : "Via a child group") },
    {
      key: "actions", label: <span className="sr-only">Actions</span>,
      render: (m) => selected && m.direct && editable(selected) ? (
        <button
          type="button" className="btn btn-sm" aria-label={`Remove ${m.name} from ${selected.name}`}
          onClick={() => act(() => groupApi.removeMember(scopeId, selected.id, m.stakeholder_id), "Removed from the group.", "Could not remove this stakeholder.")}
        >
          Remove
        </button>
      ) : null,
    },
  ];

  return (
    <div className="stack">
      <div className="row" style={{ gap: "var(--space-3)", alignSelf: "flex-start" }}>
        <button className="btn btn-primary" onClick={() => { setFormError(null); setForm({ parentId: null }); }}>
          New group
        </button>
        <button className="btn" onClick={openProposals}>Create from Organisation / group text</button>
        {organizationId && <ListActions organizationId={organizationId} recordType="stakeholder_group" onImported={reload} />}
      </div>

      <FolderTreeList<GroupNode>
        nodes={nodes}
        order="given"
        label="Stakeholder groups"
        expanded={expanded}
        onToggle={(id, open) => setCollapsed(id, !open)}
        folderIcon={() => <Users aria-hidden="true" />}
        itemView={() => ({ icon: <Users aria-hidden="true" />, iconLabel: "Stakeholder group" })}
        onOpenItem={(g) => setSelectedId(g.id)}
        isSelected={(g) => g.id === selectedId}
        columns={columns}
        emptyText="No Stakeholder groups yet. Groups classify stakeholders — for example by client or business group — and can be nested."
        renderItemActions={actionsFor}
        renderFolderActions={(node) => (node.item ? actionsFor(node.item) : null)}
      />

      {selected && (
        <div className="stack" style={{ gap: "var(--space-3)" }} aria-label={`Members of ${selected.name}`} role="region">
          <h2 style={{ margin: 0, fontSize: "1rem" }}>Members of {selected.name}</h2>
          {selected.description && <MarkdownView className="text-muted" text={selected.description} />}
          {members === null ? <Spinner /> : (
            <DirectoryTable
              ariaLabel={`Members of ${selected.name}`}
              columns={memberColumns}
              rows={shownMembers}
              rowKey={(m) => m.stakeholder_id}
              sort={memberSort}
              onSort={() => setMemberSort(cycleSort(memberSort, "name"))}
              emptyState={<p className="text-muted" style={{ margin: 0 }}>No stakeholders in this group yet.</p>}
            />
          )}
          {editable(selected) && (
            <div className="row" style={{ gap: "var(--space-3)", alignItems: "flex-end" }}>
              <LabeledSelect helpNotNeeded
                label="Stakeholder to add" value={picked} onChange={setPicked} placeholder="Choose…"
                options={candidates.filter((c) => !memberIds.has(c.value))}
              />
              <button
                className="btn" disabled={!picked}
                onClick={async () => {
                  const id = picked;
                  setPicked("");
                  await act(() => groupApi.addMember(scopeId, selected.id, id), "Added to the group.", "Could not add this stakeholder.");
                }}
              >
                Add
              </button>
            </div>
          )}
        </div>
      )}

      {form && (
        <StakeholderGroupFormModal
          initial={form.initial} groups={groups} projectId={projectId} defaultParentId={form.parentId ?? null} error={formError}
          onCancel={() => setForm(null)} onSave={saveForm}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title={`Delete ${deleting.name}?`}
          message={`This removes ${deleting.member_count} ${deleting.member_count === 1 ? "membership" : "memberships"} and moves its ${deleting.child_count} child ${deleting.child_count === 1 ? "group" : "groups"} up one level. No stakeholder is deleted.`}
          confirmLabel="Delete group"
          onConfirm={async () => {
            const group = deleting;
            setDeleting(null);
            if (await act(() => groupApi.delete(scopeId, group.id), "Group deleted.", "Could not delete this group.") && group.id === selectedId) {
              setSelectedId(null);
              setMembers(null);
            }
          }}
          onCancel={() => setDeleting(null)}
        />
      )}
      {proposals && (
        <GroupsFromTextModal proposals={proposals} error={proposalError} onCancel={() => setProposals(null)} onConfirm={confirmProposals} />
      )}
    </div>
  );
}
