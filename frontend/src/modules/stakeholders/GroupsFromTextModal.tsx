/**
 * Module: modules/stakeholders/GroupsFromTextModal
 *
 * The one-off "create groups from Organisation / group text" action:
 * lists the distinct values of the stakeholders' free-text field with how many
 * stakeholders each covers, lets the user untick any, and on confirm creates an
 * "Organisation / group" parent, a child group per ticked value and the
 * memberships that text implies. A value that already has a group is marked and
 * only tops up memberships. The free-text field itself is never changed.
 */
import { useState } from "react";

import { Modal } from "../../components/Modal";
import type { GroupTextProposal } from "./types";
import { FormActions } from "../../components/FormActions";

export function GroupsFromTextModal({
  proposals,
  error,
  onCancel,
  onConfirm,
}: {
  proposals: GroupTextProposal[];
  error?: string | null;
  onCancel: () => void;
  onConfirm: (names: string[]) => void;
}) {
  const [chosen, setChosen] = useState<Set<string>>(new Set(proposals.map((p) => p.name)));

  return (
    <Modal title="Create groups from Organisation / group text" onClose={onCancel}>
      <div className="stack">
        {proposals.length === 0 ? (
          <p className="text-muted" style={{ margin: 0 }}>No Stakeholder has an Organisation / group value yet.</p>
        ) : (
          <>
            <p className="text-muted" style={{ margin: 0 }}>
              Each ticked value becomes a group under &quot;Organisation / group&quot;, and its stakeholders are added to it.
              The text on the stakeholders is left as it is.
            </p>
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {proposals.map((p) => (
                <li key={p.name}>
                  <label className="row" style={{ gap: "0.5rem" }}>
                    <input
                      type="checkbox" aria-label={p.name} checked={chosen.has(p.name)}
                      onChange={(e) => {
                        const next = new Set(chosen);
                        if (e.target.checked) next.add(p.name);
                        else next.delete(p.name);
                        setChosen(next);
                      }}
                    />
                    <span>{p.name}</span>
                    <span className="text-muted">
                      {p.stakeholder_count} {p.stakeholder_count === 1 ? "stakeholder" : "stakeholders"}
                      {p.existing_group_id && " · group exists"}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </>
        )}
        <FormActions
          error={error}
          onCancel={onCancel}
          onSave={() => onConfirm([...chosen])}
          saveLabel="Create groups"
          saveDisabled={chosen.size === 0}
        />
      </div>
    </Modal>
  );
}
