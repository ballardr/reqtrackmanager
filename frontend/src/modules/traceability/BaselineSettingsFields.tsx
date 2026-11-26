/**
 * Module: modules/traceability/BaselineSettingsFields
 *
 * The field group that edits a baseline policy: which baselines the checks run before, whether project managers are
 * told of a refusal, which checks are enabled and, while the Required fields check is enabled, which fields a record
 * must have filled. A profile's tab and a project's section both edit through it, so a change reaches both.
 *
 * Responsibilities:
 * - Hold no state besides the open dialog: the caller owns the settings and receives each change.
 * - Add a required field through a dialog (a record type, then one of its fields) and remove one from the list; a field
 *   the offered options no longer contain still shows under its key and can be removed.
 * - Show why the settings cannot be saved (no baseline kind chosen).
 *
 * Design decisions: no empty pickers sit under the list; the add control opens on request. `fieldsSlot` lets a profile
 * place the control that chooses the project whose fields are offered.
 *
 * Dependencies: `FormFields`, `LabeledSelect`, `ItemRowList`, `ActionMenu`, `GOVERNANCE_HELP`.
 */
import { useState, type ReactNode } from "react";

import { ActionMenu } from "../../components/ActionMenu";
import { FieldCaption } from "../../components/FieldHelp";
import { FormActions } from "../../components/FormActions";
import { CheckboxField } from "../../components/FormFields";
import { InlineMessage } from "../../components/InlineMessage";
import { ItemRowList } from "../../components/ItemRowList";
import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { GOVERNANCE_HELP } from "./help";
import { baselineProblem, usesRequiredFields } from "./policyText";
import type { BaselineCheckOption, BaselineFieldOption, BaselineSettings, BaselineType, RequiredField } from "./types";

/**
 * @param settings The baseline policy being edited.
 * @param onChange Called with the new policy after any change.
 * @param checkOptions The checks that can be enabled.
 * @param types The record types a baseline can hold.
 * @param fieldOptions The fields each record type offers, keyed by record type.
 * @param fieldsSlot A control shown above the required-field list (a profile's project choice).
 */
export function BaselineSettingsFields({
  settings, onChange, checkOptions, types, fieldOptions, fieldsSlot,
}: {
  settings: BaselineSettings;
  onChange: (settings: BaselineSettings) => void;
  checkOptions: BaselineCheckOption[];
  types: BaselineType[];
  fieldOptions: Record<string, BaselineFieldOption[]>;
  fieldsSlot?: ReactNode;
}) {
  const [adding, setAdding] = useState(false);
  const typeLabel = (type: string) => types.find((t) => t.artefact_type === type)?.label ?? type;
  const fieldLabel = (type: string, key: string) => fieldOptions[type]?.find((o) => o.key === key)?.label ?? key;
  const inspects = (option: BaselineCheckOption) =>
    option.artefact_types.length === 0 ? "All record types" : `Record types: ${option.artefact_types.map(typeLabel).join(", ")}`;
  const problem = baselineProblem(settings);

  function toggleCheck(key: string, on: boolean) {
    const without = settings.checks.filter((k) => k !== key);
    onChange({ ...settings, checks: on ? [...without, key] : without });
  }

  function removeField(field: RequiredField) {
    onChange({
      ...settings,
      required_fields: settings.required_fields.filter((f) => !(f.artefact_type === field.artefact_type && f.field_key === field.field_key)),
    });
  }

  return (
    <div className="stack">
      <div className="stack" style={{ gap: "var(--space-1)" }}>
        <FieldCaption label="Baselines the checks run before" help={GOVERNANCE_HELP.baselineKinds} />
        <div className="row">
          <CheckboxField
            helpNotNeeded label="Stage baseline" checked={settings.applies_to_stage}
            onChange={(on) => onChange({ ...settings, applies_to_stage: on })}
          />
          <CheckboxField
            helpNotNeeded label="Manual baseline" checked={settings.applies_to_manual}
            onChange={(on) => onChange({ ...settings, applies_to_manual: on })}
          />
        </div>
        <InlineMessage>{problem}</InlineMessage>
      </div>
      <CheckboxField
        label="Notify project managers" help={GOVERNANCE_HELP.baselineNotify} checked={settings.notify_managers}
        onChange={(on) => onChange({ ...settings, notify_managers: on })}
      />
      <div className="stack" style={{ gap: "var(--space-1)" }}>
        <FieldCaption label="Checks" help={GOVERNANCE_HELP.baselineChecks} />
        {checkOptions.length === 0 && <p className="text-muted">No baseline checks are available.</p>}
        {checkOptions.map((option) => (
          <CheckboxField
            key={option.key} helpNotNeeded label={option.name} hint={inspects(option)} checked={settings.checks.includes(option.key)}
            onChange={(on) => toggleCheck(option.key, on)}
          />
        ))}
      </div>
      {usesRequiredFields(settings.checks) && (
        <div className="stack" style={{ gap: "var(--space-2)" }}>
          <FieldCaption label="Required fields" help={GOVERNANCE_HELP.baselineRequiredFields} />
          {fieldsSlot}
          {settings.required_fields.length === 0 && <p className="text-muted">No fields are required.</p>}
          <ItemRowList
            label="Required fields" emptyName="Field"
            items={settings.required_fields.map((field) => ({
              id: `${field.artefact_type}/${field.field_key}`,
              name: `${typeLabel(field.artefact_type)} · ${fieldLabel(field.artefact_type, field.field_key)}`,
              actions: (
                <ActionMenu
                  triggerLabel={`Actions for ${typeLabel(field.artefact_type)} · ${fieldLabel(field.artefact_type, field.field_key)}`}
                  items={[{ label: "Remove", danger: true, onSelect: () => removeField(field) }]}
                />
              ),
            }))}
          />
          <button type="button" className="btn" style={{ alignSelf: "flex-start" }} onClick={() => setAdding(true)}>
            Add required field
          </button>
        </div>
      )}
      {adding && (
        <AddRequiredFieldModal
          types={types} fieldOptions={fieldOptions} existing={settings.required_fields} onClose={() => setAdding(false)}
          onAdd={(field) => { onChange({ ...settings, required_fields: [...settings.required_fields, field] }); setAdding(false); }}
        />
      )}
    </div>
  );
}

/**
 * The dialog that adds one required field: a record type, then one of the fields it offers that is not yet required.
 *
 * @param types The record types a baseline can hold.
 * @param fieldOptions The fields each record type offers.
 * @param existing The fields already required, which are not offered again.
 * @param onAdd Called with the chosen type and field.
 * @param onClose Closes the dialog.
 */
function AddRequiredFieldModal({
  types, fieldOptions, existing, onAdd, onClose,
}: {
  types: BaselineType[];
  fieldOptions: Record<string, BaselineFieldOption[]>;
  existing: RequiredField[];
  onAdd: (field: RequiredField) => void;
  onClose: () => void;
}) {
  const [type, setType] = useState("");
  const [key, setKey] = useState("");
  const taken = new Set(existing.filter((f) => f.artefact_type === type).map((f) => f.field_key));
  const fields = (fieldOptions[type] ?? []).filter((o) => !taken.has(o.key));

  return (
    <Modal title="Add required field" onClose={onClose}>
      <div className="stack">
        <FormActions onCancel={onClose} saveLabel="Add" saveDisabled={!type || !key} onSave={() => onAdd({ artefact_type: type, field_key: key })} />
        <LabeledSelect
          required label="Record type" help={GOVERNANCE_HELP.baselineFieldType} value={type}
          onChange={(next) => { setType(next); setKey(""); }}
          options={types.map((t) => ({ value: t.artefact_type, label: t.label }))}
        />
        <LabeledSelect
          required label="Field" help={GOVERNANCE_HELP.baselineFieldKey} value={key} onChange={setKey} disabled={!type}
          options={fields.map((o) => ({ value: o.key, label: o.label }))}
        />
      </div>
    </Modal>
  );
}
