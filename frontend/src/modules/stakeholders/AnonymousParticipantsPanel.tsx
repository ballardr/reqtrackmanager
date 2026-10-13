/**
 * Module: modules/stakeholders/AnonymousParticipantsPanel
 *
 * Research extras: the participants of a session who have no Stakeholder record
 * (Phase 0 addendum 2, item 19) — a label such as "Participant 3" plus,
 * optionally, the Persona they represent. Data minimisation is the point, so the
 * form says plainly not to enter names, and the register stays free of one-time
 * participants. Add from a (+) popover; remove behind a tier-1 confirm. Persona names are
 * resolved by the server, so a hidden Persona still shows its label.
 */
import { useEffect, useState } from "react";

import { AddPopoverButton } from "../../components/AddPopoverButton";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { LabeledSelect } from "../../components/LabeledSelect";
import { RecordFieldGroup } from "../../components/RecordDetailParts";
import { RemovableItemList } from "../../components/RemovableItemList";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectResearchApi } from "./api";
import type { AnonymousParticipant } from "./types";

export function AnonymousParticipantsPanel({
  projectId,
  engagementId,
  personaOptions,
}: {
  projectId: string;
  engagementId: string;
  /** The Personas an anonymous participant can represent. */
  personaOptions: { value: string; label: string }[];
}) {
  const { showToast } = useToast();
  const [participants, setParticipants] = useState<AnonymousParticipant[] | null>(null);
  const [label, setLabel] = useState("");
  const [personaId, setPersonaId] = useState("");
  const [removing, setRemoving] = useState<AnonymousParticipant | null>(null);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let active = true;
    projectResearchApi.listAnonymousParticipants(projectId, engagementId).then((rows) => active && setParticipants(rows)).catch(() => active && setParticipants([]));
    return () => {
      active = false;
    };
  }, [projectId, engagementId, refresh]);

  async function mutate(action: () => Promise<unknown>, success: string, failure: string) {
    try {
      await action();
      showToast(success);
      setRefresh((n) => n + 1);
    } catch (err) {
      showToast(toErrorMessage(err, failure), "error");
    }
  }

  if (participants === null) return null;

  const addForm = (close: () => void) => (
    <div className="stack">
      <label className="stack" style={{ gap: "0.25rem" }}>
        <span>Participant label</span>
        <input className="input" value={label} onChange={(e) => setLabel(e.target.value)} aria-label="Participant label" autoFocus />
      </label>
      <LabeledSelect label="Persona represented" value={personaId} onChange={setPersonaId} options={personaOptions} placeholder="None" />
      <span className="text-muted" style={{ fontSize: "0.8rem" }}>
        Use a label such as “Participant 3”, not a name. Anyone who needs to be traced belongs in the Stakeholder register.
      </span>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn" onClick={close}>Cancel</button>
        <button
          className="btn btn-primary" disabled={label.trim() === ""}
          onClick={() => {
            const values = { label: label.trim(), persona_id: personaId || null };
            setLabel("");
            setPersonaId("");
            close();
            void mutate(() => projectResearchApi.addAnonymousParticipant(projectId, engagementId, values), "Participant added.", "Could not add the participant.");
          }}
        >
          Add participant
        </button>
      </div>
    </div>
  );

  return (
    <RecordFieldGroup
      label="Anonymous participants"
      gap="0.35rem"
      action={<AddPopoverButton label="Add to Anonymous participants">{addForm}</AddPopoverButton>}
    >
      {participants.length === 0 ? (
        <span className="text-muted">No anonymous participants.</span>
      ) : (
        <RemovableItemList
          items={participants.map((p) => ({
            id: p.id,
            content: <span>{p.label}{p.persona_name ? ` · ${p.persona_name}` : ""}</span>,
            removeLabel: `Remove ${p.label}`,
          }))}
          onRemove={(id) => setRemoving(participants.find((p) => p.id === id) ?? null)}
          noun="anonymous participants"
          modalTitle="Anonymous participants"
        />
      )}
      {removing && (
        <ConfirmDialog
          title={`Remove ${removing.label}?`}
          message="The participant is removed from this engagement."
          confirmLabel="Remove"
          onConfirm={() => {
            const participant = removing;
            setRemoving(null);
            void mutate(() => projectResearchApi.deleteAnonymousParticipant(projectId, engagementId, participant.id), "Participant removed.", "Could not remove the participant.");
          }}
          onCancel={() => setRemoving(null)}
        />
      )}
    </RecordFieldGroup>
  );
}
