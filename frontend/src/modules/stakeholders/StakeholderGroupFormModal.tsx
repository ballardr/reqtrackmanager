/**
 * Module: modules/stakeholders/StakeholderGroupFormModal
 *
 * Create/edit dialog for one Stakeholder group (docs/ux-style-guide.md
 * principle 3: a small entity create/edit is a `Modal`). Shared by creating a
 * top-level group, adding a child (`initial` omitted, `defaultParentId` set) and
 * editing/moving one (`initial` passed). The parent picker lists the tree
 * indented; editing offers neither the group itself nor its own descendants, so
 * a cycle cannot be built from the UI (the backend rejects one anyway).
 * "One branch per stakeholder" is the `exclusive_children` flag: it makes the
 * group behave like a single-valued column such as Client.
 */
import { useState } from "react";

import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { descendantIds, flattenGroupTree, buildGroupTree } from "./groupTree";
import { TextField } from "./RecordFormFields";
import type { StakeholderGroup, StakeholderGroupFieldValues } from "./types";

export function StakeholderGroupFormModal({
  initial,
  groups,
  defaultParentId = null,
  error,
  onCancel,
  onSave,
}: {
  initial?: StakeholderGroup;
  /** Every group this view can see, flat; the possible parents. */
  groups: StakeholderGroup[];
  defaultParentId?: string | null;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: StakeholderGroupFieldValues) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [parentId, setParentId] = useState(initial ? (initial.parent_group_id ?? "") : (defaultParentId ?? ""));
  const [exclusive, setExclusive] = useState(initial?.exclusive_children ?? false);

  const blocked = initial ? new Set([initial.id, ...descendantIds(groups, initial.id)]) : new Set<string>();
  const parentOptions = flattenGroupTree(buildGroupTree(groups))
    .filter(({ group }) => !blocked.has(group.id))
    .map(({ group, depth }) => ({ value: group.id, label: `${"  ".repeat(depth)}${group.name}` }));

  return (
    <Modal title={initial ? `Edit ${initial.name}` : "New Stakeholder group"} onClose={onCancel}>
      <div className="stack">
        <TextField label="Name" ariaLabel="Group name" value={name} onChange={setName} />
        <TextField label="Description" value={description} onChange={setDescription} />
        <LabeledSelect label="Parent group" value={parentId} onChange={setParentId} options={parentOptions} placeholder="None (top level)" />
        <label className="row" style={{ gap: "0.5rem", alignItems: "flex-start" }}>
          <input type="checkbox" checked={exclusive} onChange={(e) => setExclusive(e.target.checked)} aria-label="One branch per stakeholder" />
          <span className="stack" style={{ gap: "0.1rem" }}>
            <span>One branch per stakeholder</span>
            <span className="text-muted" style={{ fontSize: "0.8rem" }}>
              A stakeholder can be in only one of this group&apos;s direct child groups, so it can be sorted and grouped by
              like a single column (for example Client).
            </span>
          </span>
        </label>
        {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button
            className="btn btn-primary"
            disabled={name.trim() === ""}
            onClick={() =>
              onSave({ name: name.trim(), description, parent_group_id: parentId || null, exclusive_children: exclusive })
            }
          >
            Save
          </button>
        </div>
      </div>
    </Modal>
  );
}
