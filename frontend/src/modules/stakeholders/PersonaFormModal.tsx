/**
 * Module: modules/stakeholders/PersonaFormModal
 *
 * Create/edit dialog for a Persona's content fields (docs/ux-style-guide.md
 * principle 3: a full entity create/edit is a `Modal`). Shared by create and
 * edit (distinguished by whether `initial` is passed) and by the org and
 * project scopes (`scopeLabel` only changes the title).
 *
 * `owner`/`champion` are not fields here — `PersonaDetailPage` assigns
 * them through `RecordPrincipalField`. `weight` is optional: blank means "no
 * weight", which scoring treats as equal weighting. `change_note` only
 * renders when editing; "Save and activate" only when creating. Every field has a visible label (principle 13).
 */
import { useState } from "react";

import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import type { CollectedLink } from "../../api/artefactLinks";
import { Modal } from "../../components/Modal";
import { QuickLinkField } from "../../components/QuickLinkField";
import { TagField } from "../../components/TagField";
import { TextAreaField, TextField } from "../../components/FormFields";
import type { Persona, PersonaFieldValues } from "./types";
import { FormActions } from "../../components/FormActions";
import { STAKEHOLDERS_HELP } from "./help";

const TEXT_FIELDS: { key: keyof PersonaFieldValues; label: string; rows: number }[] = [
  { key: "description", label: "Description", rows: 2 },
  { key: "goals", label: "Goals", rows: 2 },
  { key: "needs", label: "Needs", rows: 2 },
  { key: "behaviours", label: "Behaviours", rows: 2 },
  { key: "context_environment", label: "Context / environment", rows: 2 },
  { key: "skills_proficiency", label: "Skills / proficiency", rows: 2 },
  { key: "frequency_of_use", label: "Frequency of use", rows: 1 },
  { key: "constraints", label: "Constraints", rows: 2 },
];

export function PersonaFormModal({
  initial,
  scopeLabel,
  projectId,
  typeOptions,
  error,
  onCancel,
  onSave,
}: {
  initial?: Persona;
  /** e.g. "organisation" / "project", shown in the title of a new persona. */
  scopeLabel: string;
  /** The project a new persona is created in; with it a create form offers the quick-link field. Omit for the organisation scope. */
  projectId?: string;
  /** The enabled types this scope offers; the current type is always kept selectable. */
  typeOptions: { value: string; label: string }[];
  error?: string | null;
  onCancel: () => void;
  onSave: (values: PersonaFieldValues, quickLinks: CollectedLink[], tags: string[]) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [typeId, setTypeId] = useState(initial?.persona_type_id ?? "");
  const [roleTitle, setRoleTitle] = useState(initial?.role_title ?? "");
  const [weight, setWeight] = useState(initial?.weight != null ? String(initial.weight) : "");
  const [changeNote, setChangeNote] = useState("");
  const [quickLinks, setQuickLinks] = useState<CollectedLink[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const [fields, setFields] = useState<Record<string, string>>(() =>
    Object.fromEntries(TEXT_FIELDS.map((f) => [f.key, (initial?.[f.key as keyof Persona] as string | undefined) ?? ""])),
  );

  const weightNumber = weight.trim() === "" ? null : Number(weight);
  const weightValid = weightNumber === null || (Number.isFinite(weightNumber) && weightNumber > 0);
  const valid = name.trim() !== "" && weightValid;

  const options =
    initial?.persona_type_id && !typeOptions.some((o) => o.value === initial.persona_type_id)
      ? [...typeOptions, { value: initial.persona_type_id, label: `${initial.persona_type_name ?? "Current type"} (disabled)` }]
      : typeOptions;

  function save(activate = false) {
    onSave({
      name: name.trim(),
      persona_type_id: typeId || null,
      role_title: roleTitle,
      weight: weightNumber,
      change_note: changeNote,
      ...(activate ? { activate: true } : {}),
      ...(Object.fromEntries(TEXT_FIELDS.map((f) => [f.key, fields[f.key] ?? ""])) as Record<string, string>),
    } as PersonaFieldValues, quickLinks, tags);
  }

  return (
    <Modal title={initial ? `Edit ${initial.name}` : `New Persona (${scopeLabel})`} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <TextField helpNotNeeded required label="Name" ariaLabel="Persona name" value={name} onChange={setName} />
          <LabeledSelect helpNotNeeded label="Type" value={typeId} onChange={setTypeId} options={options} placeholder="No type" />
          <TextField helpNotNeeded label="Role / job title" ariaLabel="Role or job title" value={roleTitle} onChange={setRoleTitle} />
          <TextField help={STAKEHOLDERS_HELP.personaImportanceWeight}
            label="Importance weight"
            ariaLabel="Importance weight"
            value={weight}
            onChange={setWeight}
            inputProps={{ min: "0", step: "any", "aria-invalid": !weightValid, type: "number" }}
          />
          {TEXT_FIELDS.map((f) => (
            <FormGridFull key={f.key}>
              <TextAreaField helpNotNeeded
                label={f.label} rows={f.rows} value={fields[f.key] ?? ""}
                onChange={(value) => setFields((prev) => ({ ...prev, [f.key]: value }))}
              />
            </FormGridFull>
          ))}
          {initial && <FormGridFull><TextField helpNotNeeded label="Change note" ariaLabel="Change note" value={changeNote} onChange={setChangeNote} /></FormGridFull>}
          {!initial && projectId && (
            <FormGridFull>
              <div className="stack">
                <QuickLinkField projectId={projectId} artefactType="persona" value={quickLinks} onChange={setQuickLinks} />
                <TagField projectId={projectId} artefactType="persona" value={tags} onChange={setTags} />
              </div>
            </FormGridFull>
          )}
        </FormGrid>
        <FormActions
          error={error} onCancel={onCancel} onSave={() => save()} saveDisabled={!valid}
          onSaveAndActivate={initial ? undefined : () => save(true)}
        />
      </div>
    </Modal>
  );
}
