/**
 * Module: modules/stakeholders/AnonymousParticipantChip
 *
 * The content of a removable chip for an anonymous participant (a label such as "Participant 3", no
 * Stakeholder record): the label, a muted "anonymous" tag and, only where the caller passes
 * `onPersonaChange`, a select for the Persona the participant represents. The engagement create form
 * passes it; the detail page does not, so its participants read like the Stakeholder ones and the
 * Persona is shown under "Personas covered". The caller owns the value (a draft in a form) and wraps
 * this in `RemovableItemList`.
 */
import { InlineSelect } from "../../components/LabeledSelect";

/** Shown with the "Add as an anonymous participant" button each time it is offered: it stops a name being recorded where a label is meant. */
export const ANONYMOUS_LABEL_NOTE =
  "Use a label such as “Participant 3”, not a name. Anyone who needs to be traced belongs in the Stakeholder register.";

/**
 * @param label The participant's label.
 * @param personaId The Persona represented, or null.
 * @param personaOptions The Personas that can be chosen.
 * @param onPersonaChange Called with the chosen Persona id, or "" for none; omit to leave the Persona out of the chip.
 */
export function AnonymousParticipantChip({
  label, personaId, personaOptions, onPersonaChange,
}: {
  label: string;
  personaId?: string | null;
  personaOptions?: { value: string; label: string }[];
  onPersonaChange?: (personaId: string) => void;
}) {
  return (
    <span className="row" style={{ gap: "var(--space-2)", flexWrap: "nowrap" }}>
      <span>{label} <span className="text-muted" style={{ fontSize: "0.75rem" }}>anonymous</span></span>
      {onPersonaChange && (
        <InlineSelect
          ariaLabel={`Persona represented by ${label}`}
          value={personaId ?? ""}
          onChange={onPersonaChange}
          options={personaOptions ?? []}
          placeholder="No Persona"
          maxWidth={200}
        />
      )}
    </span>
  );
}
