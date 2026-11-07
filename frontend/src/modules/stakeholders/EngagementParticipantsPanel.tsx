/**
 * Module: modules/stakeholders/EngagementParticipantsPanel
 *
 * The "Participants" list of an Engagement's detail page: the Stakeholders who took part and, with the
 * Research extras on, the anonymous participants (a label, optionally the Persona they represent), as
 * one row of removable chips under one heading with one (+). The (+) opens a filterable list of the
 * Stakeholders not yet recorded; choosing one adds it at once. While the extras are on, text typed that
 * matches no Stakeholder is offered as an anonymous participant. An anonymous participant's Persona is
 * chosen in the create and edit forms, so every chip here reads alike. Removal of either kind sits behind a
 * tier-1 confirm.
 *
 * Stakeholders and anonymous participants are separate records behind separate endpoints; this panel
 * only presents them together. It renders nothing when the Stakeholder participants cannot be read
 * (their sub-component is off), like the other link panels.
 */
import { Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ConfirmDialog } from "../../components/ConfirmDialog";
import { MultiSelectDropdown } from "../../components/MultiSelectDropdown";
import { RecordFieldGroup } from "../../components/RecordDetailParts";
import { RemovableItemList } from "../../components/RemovableItemList";
import { ScopedRecordCode } from "../../components/ScopedRecordCode";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { AnonymousParticipantChip, ANONYMOUS_LABEL_NOTE } from "./AnonymousParticipantChip";
import { projectEngagementApi, projectResearchApi } from "./api";
import type { AnonymousParticipant, EngagementParticipant } from "./types";

type Option = { value: string; label: string };

/** What a pending removal refers to. */
type Removal = { kind: "stakeholder"; participant: EngagementParticipant } | { kind: "anonymous"; participant: AnonymousParticipant };

/**
 * @param projectId The project of the Engagement.
 * @param engagementId The Engagement.
 * @param stakeholderOptions Every Stakeholder of the project (already-recorded ones are left out of the picker); null while unknown.
 * @param researchExtras Whether anonymous participants are available.
 * @param showCodes Whether each Stakeholder is preceded by its record code.
 * @param reloadKey Change to force a reload from outside (an audience group copied members in).
 * @param onChanged Called after any change, so the Links panel can refresh.
 */
export function EngagementParticipantsPanel({
  projectId, engagementId, stakeholderOptions, researchExtras, showCodes, reloadKey, onChanged,
}: {
  projectId: string;
  engagementId: string;
  stakeholderOptions: Option[] | null;
  researchExtras: boolean;
  showCodes: boolean;
  reloadKey: number;
  onChanged: () => void;
}) {
  const { showToast } = useToast();
  const [stakeholders, setStakeholders] = useState<EngagementParticipant[] | null>(null);
  const [anonymous, setAnonymous] = useState<AnonymousParticipant[]>([]);
  const [unavailable, setUnavailable] = useState(false);
  const [removing, setRemoving] = useState<Removal | null>(null);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let active = true;
    projectEngagementApi.listParticipants(projectId, engagementId)
      .then((rows) => active && (setStakeholders(rows), setUnavailable(false)))
      .catch(() => active && setUnavailable(true));
    if (researchExtras) {
      projectResearchApi.listAnonymousParticipants(projectId, engagementId)
        .then((rows) => active && setAnonymous(rows))
        .catch(() => active && setAnonymous([]));
    }
    return () => {
      active = false;
    };
  }, [projectId, engagementId, researchExtras, refresh, reloadKey]);

  async function mutate(action: () => Promise<unknown>, success: string, failure: string) {
    try {
      await action();
      showToast(success);
      setRefresh((n) => n + 1);
      onChanged();
    } catch (err) {
      showToast(toErrorMessage(err, failure), "error");
    }
  }

  if (unavailable || stakeholders === null) return null;

  const recorded = new Set(stakeholders.map((p) => p.stakeholder_id));
  const candidates = (stakeholderOptions ?? []).filter((o) => !recorded.has(o.value));
  const noStakeholders = stakeholderOptions?.length === 0;

  const shownAnonymous = researchExtras ? anonymous : [];
  const items = [
    ...stakeholders.map((p) => ({
      id: `stakeholder:${p.link_id}`,
      content: (
        <>
          {showCodes && p.unique_code && (
            <span className="text-muted" style={{ fontSize: "0.85rem" }}>
              <ScopedRecordCode record={{ unique_code: p.unique_code, scope: p.scope, organization_id: p.organization_id }} />{" "}
            </span>
          )}
          <Link to={`/projects/${projectId}/modules/stakeholders/stakeholders/${p.stakeholder_id}`}>{p.name}</Link>
        </>
      ),
      removeLabel: `Remove ${p.name}`,
    })),
    ...shownAnonymous.map((p) => ({
      id: `anonymous:${p.id}`,
      content: <AnonymousParticipantChip label={p.label} />,
      removeLabel: `Remove ${p.label}`,
    })),
  ];
  const removalName = removing ? (removing.kind === "stakeholder" ? removing.participant.name : removing.participant.label) : "";

  return (
    <RecordFieldGroup
      helpNotNeeded
      label="Participants"
      gap="0.35rem"
      action={
        <MultiSelectDropdown
          triggerLabel="Add to Participants"
          icon={<Plus size={14} aria-hidden="true" />}
          disabled={candidates.length === 0 && !researchExtras}
          filterable
          options={candidates.map((o) => ({
            value: o.value, label: o.label, optionLabel: `Participant ${o.label}`, checked: false,
            onToggle: () => void mutate(() => projectEngagementApi.addParticipant(projectId, engagementId, o.value), "Participant added.", "Could not add the participant."),
          }))}
          addFromFilter={researchExtras ? {
            label: (text) => `Add “${text}” as an anonymous participant`,
            note: ANONYMOUS_LABEL_NOTE,
            onAdd: (label) => void mutate(() => projectResearchApi.addAnonymousParticipant(projectId, engagementId, { label }), "Participant added.", "Could not add the participant."),
          } : undefined}
        />
      }
    >
      {items.length === 0 ? (
        <span className="text-muted">Nobody is recorded as taking part.</span>
      ) : (
        <RemovableItemList
          items={items}
          onRemove={(id) => {
            const [kind, key] = id.split(":");
            if (kind === "stakeholder") {
              const participant = stakeholders.find((p) => p.link_id === key);
              if (participant) setRemoving({ kind: "stakeholder", participant });
            } else {
              const participant = anonymous.find((p) => p.id === key);
              if (participant) setRemoving({ kind: "anonymous", participant });
            }
          }}
          noun="participants"
          modalTitle="Participants"
        />
      )}
      {noStakeholders && !researchExtras && (
        <span className="text-muted">
          No Stakeholders exist in this project yet. <Link to={`/projects/${projectId}/modules/stakeholders/stakeholders`}>Add a Stakeholder</Link> to record who took part.
        </span>
      )}
      {removing && (
        <ConfirmDialog
          title={`Remove ${removalName}?`}
          message={removing.kind === "stakeholder" ? "The two records stay; only the link between them is removed." : "The participant is removed from this engagement."}
          confirmLabel="Remove"
          onConfirm={() => {
            const current = removing;
            setRemoving(null);
            void mutate(
              () => current.kind === "stakeholder"
                ? projectEngagementApi.removeParticipant(projectId, engagementId, current.participant.stakeholder_id)
                : projectResearchApi.deleteAnonymousParticipant(projectId, engagementId, current.participant.id),
              current.kind === "stakeholder" ? "Link removed." : "Participant removed.", "Could not remove the participant.",
            );
          }}
          onCancel={() => setRemoving(null)}
        />
      )}
    </RecordFieldGroup>
  );
}
