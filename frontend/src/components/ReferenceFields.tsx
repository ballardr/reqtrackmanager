/**
 * Module: components/ReferenceFields
 *
 * The fields of one external reference: the system it lives in, its key, its link, its role and a note. The one field
 * group behind both places a reference is edited (the create form's `ReferenceField` rows and the record page's
 * `ReferenceFormModal`), so they cannot drift. The caller owns the draft.
 */
import { EXTERNAL_REFERENCE_ROLES, EXTERNAL_REFERENCE_ROLE_LABEL, type ExternalReferenceRole, type ReferenceSystem } from "../api/externalReferences";
import { useStrings } from "../context/TerminologyContext";
import { TextField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import type { ReferenceDraft } from "./referenceDraft";

/**
 * @param draft The reference being edited.
 * @param onChange Called with the next draft.
 * @param systems The systems that can be chosen.
 * @param ordinal Distinguishes this reference's fields when several are on screen (their accessible names); omit for one.
 */
export function ReferenceFields({
  draft, onChange, systems, ordinal,
}: { draft: ReferenceDraft; onChange: (next: ReferenceDraft) => void; systems: ReferenceSystem[]; ordinal?: number }) {
  const strings = useStrings().references;
  const help = useStrings().help;
  const set = <K extends keyof ReferenceDraft>(key: K, value: ReferenceDraft[K]) => onChange({ ...draft, [key]: value });
  return (
    <>
      <LabeledSelect
        required help={help.referenceSystem} label={strings.system} ariaLabel={ordinal ? strings.systemLabelOf(ordinal) : undefined}
        value={draft.systemId} onChange={(v) => set("systemId", v)} options={systems.map((s) => ({ value: s.id, label: s.name }))}
        placeholder={strings.systemChoose}
      />
      <TextField
        help={help.referenceKey} label={strings.key} ariaLabel={ordinal ? strings.keyLabelOf(ordinal) : undefined}
        placeholder={strings.keyPlaceholder} hint={strings.keyHint} value={draft.key} onChange={(v) => set("key", v)}
      />
      <TextField
        help={help.referenceLink} label={strings.link} ariaLabel={ordinal ? strings.linkLabelOf(ordinal) : undefined}
        placeholder={strings.linkPlaceholder} value={draft.url} onChange={(v) => set("url", v)}
      />
      <LabeledSelect
        help={help.referenceRole} label={strings.role} ariaLabel={ordinal ? strings.roleLabelOf(ordinal) : undefined}
        value={draft.role} placeholder={strings.roleNone} onChange={(v) => set("role", v as ExternalReferenceRole | "")}
        options={EXTERNAL_REFERENCE_ROLES.map((role) => ({ value: role, label: EXTERNAL_REFERENCE_ROLE_LABEL[role] }))}
      />
      <TextField
        help={help.referenceNote} label={strings.note} ariaLabel={ordinal ? strings.noteLabelOf(ordinal) : undefined}
        value={draft.note} onChange={(v) => set("note", v)}
      />
    </>
  );
}
