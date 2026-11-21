/**
 * Module: components/CustomFieldCreateModal
 *
 * The dialog that adds a custom field to a project, opened by Project Administration's "New field" button so the
 * Custom fields section shows no empty fields until someone asks (docs/ux-style-guide.md, "Pattern: creation controls
 * on demand").
 *
 * Responsibilities:
 * - Collect which kind of record the field belongs to, its name, type, options (a list type only) and whether it is
 *   required, and hand them to `onCreate`.
 * - Close only when `onCreate` reports success; a refusal is already toasted by the caller.
 */
import { useState } from "react";

import { CUSTOM_FIELD_TYPE_LABEL, type CustomFieldEntityKind, type CustomFieldType } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { FormActions } from "./FormActions";
import { CheckboxField, TextField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";

/** What the dialog collects; `options` is the comma-separated text of a list field. */
export interface CustomFieldDraft {
  entityKind: CustomFieldEntityKind;
  name: string;
  fieldType: CustomFieldType;
  options: string;
  required: boolean;
}

const FIELD_TYPES: CustomFieldType[] = ["short_text", "long_text", "checkbox", "list"];

/**
 * @param onCreate Creates the field; resolves true when it exists (the dialog then closes).
 * @param onClose Closes the dialog.
 */
export function CustomFieldCreateModal({
  onCreate, onClose,
}: {
  onCreate: (draft: CustomFieldDraft) => Promise<boolean>;
  onClose: () => void;
}) {
  const strings = useStrings();
  const [draft, setDraft] = useState<CustomFieldDraft>({ entityKind: "requirement", name: "", fieldType: "short_text", options: "", required: false });
  const [busy, setBusy] = useState(false);
  const valid = draft.name.trim() !== "";
  const patch = (change: Partial<CustomFieldDraft>) => setDraft((current) => ({ ...current, ...change }));

  async function save() {
    if (!valid || busy) return;
    setBusy(true);
    const created = await onCreate(draft);
    setBusy(false);
    if (created) onClose();
  }

  return (
    <Modal title={strings.admin.newCustomField} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); void save(); }}>
        <LabeledSelect help={strings.help.customFieldAppliesTo}
          label={strings.admin.fieldAppliesTo}
          value={draft.entityKind}
          onChange={(next) => patch({ entityKind: next as CustomFieldEntityKind })}
          options={[
            { value: "requirement", label: strings.admin.entityKindRequirement },
            { value: "change_request", label: strings.admin.entityKindChangeRequest },
          ]}
          placeholder={null}
        />
        <TextField helpNotNeeded required label={strings.admin.fieldName} value={draft.name} onChange={(name) => patch({ name })} inputProps={{ autoFocus: true }} />
        <LabeledSelect help={strings.help.customFieldType}
          label={strings.admin.fieldTypeLabel}
          value={draft.fieldType}
          onChange={(next) => patch({ fieldType: next as CustomFieldType })}
          options={FIELD_TYPES.map((value) => ({ value, label: CUSTOM_FIELD_TYPE_LABEL[value] }))}
          placeholder={null}
        />
        {draft.fieldType === "list" && (
          <TextField help={strings.help.customFieldOptions}
            label={strings.admin.optionsCommaSeparated}
            value={draft.options}
            onChange={(options) => patch({ options })}
          />
        )}
        <CheckboxField help={strings.help.customFieldRequired} label={strings.admin.required} checked={draft.required} onChange={(required) => patch({ required })} />
        <FormActions onCancel={onClose} onSave={() => void save()} saveLabel={strings.common.add} saveDisabled={!valid || busy} />
      </form>
    </Modal>
  );
}
