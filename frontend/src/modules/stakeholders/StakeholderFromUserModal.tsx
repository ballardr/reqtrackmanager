/**
 * Module: modules/stakeholders/StakeholderFromUserModal
 *
 * "Add from org user" (Phase 0 resolution 13): picks an organisation member and
 * creates a Stakeholder for them with their name and email prefilled, linked to
 * their account (`user_id`). It removes the friction of retyping a colleague
 * who is also a stakeholder; most stakeholders have no account and use the
 * ordinary create form instead. Optional role and type can be set up front;
 * everything else is edited afterwards.
 */
import { useState } from "react";

import type { OrgUser } from "../../api/types";
import { AssigneePicker } from "../../components/AssigneePicker";
import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { TextField } from "./RecordFormFields";

export function StakeholderFromUserModal({
  scopeLabel,
  orgUsers,
  typeOptions,
  error,
  onCancel,
  onSave,
}: {
  /** e.g. "organisation" / "project", shown in the title. */
  scopeLabel: string;
  orgUsers: OrgUser[];
  typeOptions: { value: string; label: string }[];
  error?: string | null;
  onCancel: () => void;
  onSave: (values: { user_id: string; stakeholder_type_id: string | null; role: string }) => void;
}) {
  const [userId, setUserId] = useState<string | null>(null);
  const [typeId, setTypeId] = useState("");
  const [role, setRole] = useState("");

  return (
    <Modal title={`Add Stakeholder from organisation user (${scopeLabel})`} onClose={onCancel}>
      <div className="stack">
        <p className="text-muted" style={{ margin: 0 }}>
          Creates a Stakeholder with this person's name and email filled in, linked to their account.
        </p>
        <div className="stack" style={{ gap: "0.25rem" }}>
          <span>Organisation user</span>
          <AssigneePicker
            orgUsers={orgUsers} assigneeId={userId} onChange={(id) => setUserId(id || null)}
            ariaLabel="Organisation user" placeholder="Search users…"
          />
        </div>
        <LabeledSelect label="Type" value={typeId} onChange={setTypeId} options={typeOptions} placeholder="No type" />
        <TextField label="Role" value={role} onChange={setRole} />
        {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button
            className="btn btn-primary" disabled={!userId}
            onClick={() => userId && onSave({ user_id: userId, stakeholder_type_id: typeId || null, role })}
          >
            Add Stakeholder
          </button>
        </div>
      </div>
    </Modal>
  );
}
