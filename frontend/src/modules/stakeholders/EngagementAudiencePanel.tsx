/**
 * Module: modules/stakeholders/EngagementAudiencePanel
 *
 * The Stakeholder groups an engagement was aimed at.
 * Picking groups in the shared `TreeSelect` and pressing "Add everyone in
 * group" records an audience link and copies each group's current members
 * (descendants included) into the participant list as a **snapshot**: the
 * engagement is a historical record, so later membership changes never alter who
 * attended, and a no-show is removed from the participants as usual. Removing an
 * audience removes the link only; the participants it added stay (the confirm
 * says so). The toast reports how many people were added and how many were
 * already taking part. Any group of the organisation or the project can be
 * chosen, so no node is disabled. The tree picker opens its own popover, and popovers do not nest,
 * so the (+) button opens a small `Modal` rather than a `Popover`.
 */
import { Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Modal } from "../../components/Modal";
import { RecordFieldGroup } from "../../components/RecordDetailParts";
import { RemovableItemList } from "../../components/RemovableItemList";
import { TreeSelect } from "../../components/TreeSelect";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectEngagementApi } from "./api";
import { allGroupSelectNodes, buildGroupTree, groupPath } from "./groupTree";
import type { EngagementAudience, StakeholderGroup } from "./types";

export function EngagementAudiencePanel({
  projectId,
  engagementId,
  groups,
  onParticipantsChanged,
  onChanged,
}: {
  projectId: string;
  engagementId: string;
  /** Every group the project can see, flat. */
  groups: StakeholderGroup[];
  /** Called after members are copied in, so the participant list reloads. */
  onParticipantsChanged: () => void;
  /** Called after an audience is added or removed, so a page's Links panel can refresh. */
  onChanged?: () => void;
}) {
  const { showToast } = useToast();
  const [audiences, setAudiences] = useState<EngagementAudience[] | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [removing, setRemoving] = useState<EngagementAudience | null>(null);
  const [adding, setAdding] = useState(false);
  const [picking, setPicking] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    projectEngagementApi.listAudiences(projectId, engagementId).then((rows) => active && setAudiences(rows)).catch(() => active && setAudiences([]));
    return () => {
      active = false;
    };
  }, [projectId, engagementId, refresh]);

  const audienceIds = new Set((audiences ?? []).map((a) => a.group_id));
  const nodes = allGroupSelectNodes(buildGroupTree(groups.filter((g) => !audienceIds.has(g.id))));

  async function addEveryone() {
    setAdding(true);
    setPicking(false);
    const wanted = selected;
    setSelected([]);
    let added = 0;
    let already = 0;
    try {
      for (const groupId of wanted) {
        const result = await projectEngagementApi.addAudience(projectId, engagementId, groupId);
        added += result.participants_added.length;
        already += result.already_participating;
      }
      showToast(`Added ${added} ${added === 1 ? "person" : "people"} as participants${already ? ` (${already} already taking part)` : ""}.`);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not add everyone in the group."), "error");
    } finally {
      if (mounted.current) {
        setAdding(false);
        setRefresh((n) => n + 1);
      }
      onParticipantsChanged();
      onChanged?.();
    }
  }

  async function removeAudience(audience: EngagementAudience) {
    try {
      await projectEngagementApi.removeAudience(projectId, engagementId, audience.group_id);
      showToast("Audience removed.");
      setRefresh((n) => n + 1);
      onChanged?.();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not remove the audience."), "error");
    }
  }

  if (audiences === null) return null;

  return (
    <RecordFieldGroup
      label="Audience groups"
      gap="0.35rem"
      action={
        <button
          type="button" className="btn btn-sm btn-icon" aria-label="Add to Audience groups"
          title="Add to Audience groups" aria-haspopup="dialog" disabled={nodes.length === 0} onClick={() => setPicking(true)}
        >
          <Plus aria-hidden="true" />
        </button>
      }
    >
      {audiences.length === 0 ? (
        <span className="text-muted">Not aimed at a group.</span>
      ) : (
        <RemovableItemList
          items={audiences.map((a) => ({
            id: a.link_id,
            content: <span title={groupPath(groups, a.group_id)}>{a.name}</span>,
            removeLabel: `Remove audience ${a.name}`,
          }))}
          onRemove={(id) => setRemoving(audiences.find((a) => a.link_id === id) ?? null)}
          noun="groups"
          modalTitle="Audience groups"
        />
      )}
      {picking && (
        <Modal title="Add everyone in a group" onClose={() => { setPicking(false); setSelected([]); }}>
          <div className="stack">
            <TreeSelect triggerLabel="Groups to add" nodes={nodes} selectedIds={selected} onChange={setSelected} emptyLabel="Choose groups…" />
            <span className="text-muted" style={{ fontSize: "0.8rem" }}>
              Copies the group's current members in as participants. Later changes to the group don't change who took part.
            </span>
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button className="btn" onClick={() => { setPicking(false); setSelected([]); }}>Cancel</button>
              <button className="btn btn-primary" disabled={selected.length === 0 || adding} onClick={addEveryone}>
                Add everyone in group
              </button>
            </div>
          </div>
        </Modal>
      )}
      {removing && (
        <ConfirmDialog
          title={`Remove audience ${removing.name}?`}
          message="Only the link to the group is removed. The people it added stay as participants; remove them individually if they did not attend."
          confirmLabel="Remove"
          onConfirm={() => {
            const audience = removing;
            setRemoving(null);
            void removeAudience(audience);
          }}
          onCancel={() => setRemoving(null)}
        />
      )}
    </RecordFieldGroup>
  );
}
