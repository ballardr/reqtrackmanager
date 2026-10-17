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
 * In a project the tree also shows the organisation's groups, marked
 * "Organisation" and read-only (they are edited from the organisation view); a
 * project group can be created under one. Deleting is a tier-1 `ConfirmDialog`
 * that states the member and child counts, since it removes memberships and
 * moves child groups up but never deletes a stakeholder. Every mutating control
 * always renders; the backend enforces the Stakeholder manage permission and a
 * 403 surfaces as a toast.
 */
import { ArrowDown, ArrowUp, Pencil, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ConfirmDialog } from "../../components/ConfirmDialog";
import { LabeledSelect } from "../../components/LabeledSelect";
import { Spinner } from "../../components/Spinner";
import { TreeView } from "../../components/TreeView";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { orgStakeholderApi, orgStakeholderGroupApi, projectStakeholderApi, projectStakeholderGroupApi } from "./api";
import { type GroupNode, buildGroupTree } from "./groupTree";
import { GroupsFromTextModal } from "./GroupsFromTextModal";
import { StakeholderGroupFormModal } from "./StakeholderGroupFormModal";
import type {
  GroupTextProposal, StakeholderGroup, StakeholderGroupFieldValues, StakeholderGroupMember,
} from "./types";
import { STAKEHOLDER_SCOPE_LABEL } from "./types";
import { Badge } from "../../components/Badge";

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
        if (active) setLoadError(toErrorMessage(err, "The Stakeholders & Personas module isn't enabled here, or you don't have access to it."));
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
  const selected = groups?.find((g) => g.id === selectedId) ?? null;
  const editable = (g: StakeholderGroup) => g.scope === tier;

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

  async function saveForm(values: StakeholderGroupFieldValues) {
    setFormError(null);
    try {
      if (form?.initial) await groupApi.update(scopeId, form.initial.id, values);
      else await groupApi.create(scopeId, values);
      showToast(form?.initial ? "Group updated." : "Group created.");
      setForm(null);
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

  return (
    <div className="stack">
      <div className="row" style={{ gap: "0.5rem", alignSelf: "flex-start" }}>
        <button className="btn btn-primary" onClick={() => { setFormError(null); setForm({ parentId: null }); }}>
          New group
        </button>
        <button className="btn" onClick={openProposals}>Create from Organisation / group text</button>
      </div>

      {groups.length === 0 ? (
        <p className="text-muted">
          No Stakeholder groups yet. Groups classify stakeholders — for example by client or business group — and
          can be nested.
        </p>
      ) : (
        <div role="tree" aria-label="Stakeholder groups">
          <TreeView<GroupNode>
            nodes={tree}
            nodeLabel={(n) => n.name}
            renderNode={(n) => (
              <span className="row" style={{ gap: "0.35rem", alignItems: "center" }}>
                <button
                  className="btn" style={{ fontWeight: n.id === selectedId ? 700 : 400 }}
                  aria-pressed={n.id === selectedId} onClick={() => setSelectedId(n.id)}
                >
                  {n.name}
                </button>
                <span className="text-muted">{n.member_count}</span>
                {n.scope !== tier && <Badge>{STAKEHOLDER_SCOPE_LABEL[n.scope]}</Badge>}
                {n.exclusive_children && <Badge title="A stakeholder can be in only one child group.">One branch</Badge>}
                {editable(n) && (
                  <>
                    <button className="btn btn-sm btn-icon" title={`Add a group under ${n.name}`} aria-label={`Add a group under ${n.name}`}
                      onClick={() => { setFormError(null); setForm({ parentId: n.id }); }}><Plus /></button>
                    <button className="btn btn-sm btn-icon" title={`Edit ${n.name}`} aria-label={`Edit ${n.name}`}
                      onClick={() => { setFormError(null); setForm({ initial: n }); }}><Pencil /></button>
                    <button className="btn btn-sm btn-icon" title={`Move ${n.name} up`} aria-label={`Move ${n.name} up`}
                      onClick={() => act(() => groupApi.move(scopeId, n.id, "up"), "Group moved.", "Could not move this group.")}><ArrowUp /></button>
                    <button className="btn btn-sm btn-icon" title={`Move ${n.name} down`} aria-label={`Move ${n.name} down`}
                      onClick={() => act(() => groupApi.move(scopeId, n.id, "down"), "Group moved.", "Could not move this group.")}><ArrowDown /></button>
                    <button className="btn btn-sm btn-icon" title={`Delete ${n.name}`} aria-label={`Delete ${n.name}`}
                      onClick={() => setDeleting(n)}><Trash2 /></button>
                  </>
                )}
              </span>
            )}
          />
        </div>
      )}

      {selected && (
        <div className="stack" style={{ gap: "0.5rem" }} aria-label={`Members of ${selected.name}`} role="region">
          <h2 style={{ margin: 0, fontSize: "1rem" }}>Members of {selected.name}</h2>
          {selected.description && <p className="text-muted" style={{ margin: 0 }}>{selected.description}</p>}
          {members === null ? <Spinner /> : members.length === 0 ? (
            <p className="text-muted" style={{ margin: 0 }}>No stakeholders in this group yet.</p>
          ) : (
            <ul style={{ margin: 0, paddingLeft: "1.25rem" }}>
              {members.map((m) => (
                <li key={m.stakeholder_id}>
                  {m.name}
                  {!m.direct && <span className="text-muted"> · via a child group</span>}
                  {m.direct && editable(selected) && (
                    <button
                      className="btn" style={{ marginLeft: "0.5rem" }} aria-label={`Remove ${m.name} from ${selected.name}`}
                      onClick={() => act(() => groupApi.removeMember(scopeId, selected.id, m.stakeholder_id), "Removed from the group.", "Could not remove this stakeholder.")}
                    >
                      Remove
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
          {editable(selected) && (
            <div className="row" style={{ gap: "0.5rem", alignItems: "flex-end" }}>
              <LabeledSelect
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
          initial={form.initial} groups={groups} defaultParentId={form.parentId ?? null} error={formError}
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
