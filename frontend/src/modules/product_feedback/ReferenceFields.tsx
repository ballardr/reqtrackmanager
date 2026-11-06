/**
 * Module: modules/product_feedback/ReferenceFields
 *
 * The fields of one external reference — the system it lives in, its key, its link and whether the request came from
 * there or is delivered there. The one field group behind both places a reference is edited (the create form's
 * `ReferencesField` rows and the detail page's `ReferenceFormModal`), so they cannot drift. The caller owns the draft.
 */
import { TextField } from "../../components/FormFields";
import { LabeledSelect } from "../../components/LabeledSelect";
import { PRODUCT_FEEDBACK_HELP } from "./help";
import type { ReferenceDraft } from "./referenceDraft";
import { EXTERNAL_REF_ROLES, EXTERNAL_REF_ROLE_LABEL, type ExternalRefRole } from "./types";
import type { ListChoice } from "./useFeedbackLists";

/**
 * @param draft The reference being edited.
 * @param onChange Called with the next draft.
 * @param systems The external systems that can be chosen.
 * @param label Distinguishes this reference's fields when several are on screen (their accessible names), e.g. "Reference 2".
 */
export function ReferenceFields({
  draft, onChange, systems, label = "Reference",
}: {
  draft: ReferenceDraft;
  onChange: (next: ReferenceDraft) => void;
  systems: ListChoice[];
  label?: string;
}) {
  const set = <K extends keyof ReferenceDraft>(key: K, value: ReferenceDraft[K]) => onChange({ ...draft, [key]: value });
  return (
    <>
      <LabeledSelect
        required help={PRODUCT_FEEDBACK_HELP.referenceSystem} label="System" ariaLabel={`${label} system`}
        value={draft.systemId} onChange={(v) => set("systemId", v)} options={systems} placeholder="Choose a system…"
      />
      <TextField
        help={PRODUCT_FEEDBACK_HELP.referenceKey} label="Key" ariaLabel={`${label} key`} placeholder="PROJ-123"
        hint="Give a key, a link, or both." value={draft.key} onChange={(v) => set("key", v)}
      />
      <TextField
        help={PRODUCT_FEEDBACK_HELP.referenceUrl} label="Link" ariaLabel={`${label} link`} placeholder="https://…"
        value={draft.url} onChange={(v) => set("url", v)}
      />
      <LabeledSelect
        help={PRODUCT_FEEDBACK_HELP.referenceRole} label="Role" ariaLabel={`${label} role`} value={draft.role} placeholder={null}
        onChange={(v) => set("role", v as ExternalRefRole)}
        options={EXTERNAL_REF_ROLES.map((role) => ({ value: role, label: EXTERNAL_REF_ROLE_LABEL[role] }))}
      />
    </>
  );
}
