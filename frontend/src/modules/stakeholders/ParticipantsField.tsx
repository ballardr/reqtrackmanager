/**
 * Module: modules/stakeholders/ParticipantsField
 *
 * The "Participants" field of the engagement create and edit forms, laid out like the detail page's lists: a
 * (+) beside the caption opens a filterable checklist of the project's Stakeholders, and the chosen
 * people are chips beneath. With the Research extras on, text typed in the checklist that is not a
 * known Stakeholder is offered as an anonymous participant (a label such as "Participant 3", no
 * Stakeholder record); its chip carries a Persona select, so a participant first recorded without a
 * Persona (a late arrival, a name not yet known) can be given one later. Nothing is written here; the
 * form owns the lists. A new engagement sends them in the create request; an edit compares them with
 * what was recorded (`engagementParticipantEdits`). The detail page's Participants list adds and
 * removes people directly.
 *
 * It loads the project's Stakeholders itself and renders nothing when they cannot be read (a
 * form never offers a field the request would refuse). A project with no Stakeholders and no
 * Research extras shows an empty state naming the next step instead of an empty dropdown.
 */
import { Plus } from "lucide-react";
import { useEffect, useState } from "react";

import { FieldShell } from "../../components/FieldHelp";
import { MultiSelectDropdown } from "../../components/MultiSelectDropdown";
import { RemovableItemList } from "../../components/RemovableItemList";
import { AnonymousParticipantChip, ANONYMOUS_LABEL_NOTE } from "./AnonymousParticipantChip";
import { projectPersonaApi, projectStakeholderApi } from "./api";
import { STAKEHOLDERS_HELP } from "./help";
import type { AnonymousParticipantEntry, Stakeholder } from "./types";
import { useResearchExtras } from "./useResearchExtras";

const CONTROL_ID = "engagement-participants";
const ANONYMOUS_PREFIX = "anonymous:";

/**
 * @param projectId The project of the engagement.
 * @param value The Stakeholder ids chosen so far; the form owns them.
 * @param onChange Called with the new list.
 * @param anonymous The anonymous participants entered so far; the form owns them.
 * @param onAnonymousChange Called with the new list.
 * @param load Injectable Stakeholder list call (stories pass a fake).
 */
export function ParticipantsField({
  projectId, value, onChange, anonymous, onAnonymousChange, load = projectStakeholderApi.list,
}: {
  projectId: string;
  value: string[];
  onChange: (ids: string[]) => void;
  anonymous: AnonymousParticipantEntry[];
  onAnonymousChange: (next: AnonymousParticipantEntry[]) => void;
  load?: (projectId: string) => Promise<Stakeholder[]>;
}) {
  const extras = useResearchExtras(projectId) === true;
  const [stakeholders, setStakeholders] = useState<Stakeholder[] | null>(null);
  const [personas, setPersonas] = useState<{ value: string; label: string }[]>([]);

  useEffect(() => {
    let active = true;
    load(projectId).then((rows) => active && setStakeholders(rows)).catch(() => active && setStakeholders(null));
    return () => {
      active = false;
    };
  }, [projectId, load]);

  useEffect(() => {
    if (!extras) return;
    let active = true;
    projectPersonaApi.list(projectId)
      .then((rows) => active && setPersonas(rows.map((p) => ({ value: p.id, label: p.name }))))
      .catch(() => active && setPersonas([]));
    return () => {
      active = false;
    };
  }, [projectId, extras]);

  if (stakeholders === null) return null;
  const chosen = new Set(value);
  const addAnonymous = (label: string) => {
    if (anonymous.some((p) => p.label.toLowerCase() === label.toLowerCase())) return;
    onAnonymousChange([...anonymous, { label, persona_id: null }]);
  };
  const setPersona = (index: number, personaId: string) =>
    onAnonymousChange(anonymous.map((p, i) => (i === index ? { ...p, persona_id: personaId || null } : p)));
  // A Persona hidden from the project is not in the list, so its recorded name keeps it selectable.
  const personaChoices = (p: AnonymousParticipantEntry) =>
    p.persona_id && !personas.some((o) => o.value === p.persona_id)
      ? [...personas, { value: p.persona_id, label: p.persona_name ?? "Hidden Persona" }]
      : personas;

  const stakeholderItems = stakeholders.filter((s) => chosen.has(s.id));
  const removeItem = (id: string) => {
    if (id.startsWith(ANONYMOUS_PREFIX)) onAnonymousChange(anonymous.filter((_, i) => `${ANONYMOUS_PREFIX}${i}` !== id));
    else onChange(value.filter((stakeholderId) => stakeholderId !== id));
  };
  const items = [
    ...stakeholderItems.map((s) => ({ id: s.id, content: <span>{s.name}</span>, removeLabel: `Remove ${s.name}` })),
    ...anonymous.map((p, index) => ({
      id: `${ANONYMOUS_PREFIX}${index}`,
      content: <AnonymousParticipantChip label={p.label} personaId={p.persona_id} personaOptions={personaChoices(p)} onPersonaChange={(id) => setPersona(index, id)} />,
      removeLabel: `Remove ${p.label}`,
    })),
  ];
  const picker = (
    <MultiSelectDropdown
      id={CONTROL_ID}
      triggerLabel="Add to Participants"
      icon={<Plus size={14} aria-hidden="true" />}
      filterable
      options={[
        ...stakeholders.map((s) => ({
          value: s.id,
          label: s.name,
          optionLabel: `Participant ${s.name}`,
          checked: chosen.has(s.id),
          onToggle: () => onChange(chosen.has(s.id) ? value.filter((id) => id !== s.id) : [...value, s.id]),
        })),
        ...anonymous.map((p, index) => ({
          value: `${ANONYMOUS_PREFIX}${index}`,
          label: p.label,
          hint: "anonymous",
          optionLabel: `Anonymous participant ${p.label}`,
          checked: true,
          onToggle: () => onAnonymousChange(anonymous.filter((_, i) => i !== index)),
        })),
      ]}
      addFromFilter={extras ? { label: (text) => `Add “${text}” as an anonymous participant`, onAdd: addAnonymous, note: ANONYMOUS_LABEL_NOTE } : undefined}
    />
  );

  return (
    <FieldShell
      label="Participants" controlId={CONTROL_ID} extra={stakeholders.length === 0 && !extras ? undefined : picker}
      help={extras ? STAKEHOLDERS_HELP.engagementParticipantsWithAnonymous : STAKEHOLDERS_HELP.engagementParticipants}
    >
      {stakeholders.length === 0 && !extras ? (
        <span className="text-muted">No Stakeholders exist in this project yet. Add them on the Stakeholders page, then record who took part.</span>
      ) : items.length === 0 ? (
        <span className="text-muted">No participants added.</span>
      ) : (
        <RemovableItemList items={items} onRemove={removeItem} noun="participants" modalTitle="Participants" />
      )}
    </FieldShell>
  );
}
