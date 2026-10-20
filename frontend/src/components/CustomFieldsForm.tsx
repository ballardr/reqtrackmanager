import type { CustomFieldDefinition } from "../api/types";
import { CheckboxField, TextAreaField, TextField } from "./FormFields";
import { FormGrid, FormGridFull } from "./FormGrid";
import { LabeledSelect } from "./LabeledSelect";

/**
 * Renders dynamic form fields for a project's custom attribute definitions
 * (C-C-01, C-C-02), keyed by definition id — used on requirement and change
 * request create/edit forms.
 */
export function CustomFieldsForm({
  definitions,
  values,
  onChange,
  disabled,
}: {
  definitions: CustomFieldDefinition[];
  values: Record<string, unknown>;
  onChange: (fieldId: string, value: unknown) => void;
  disabled?: boolean;
}) {
  if (definitions.length === 0) return null;

  return (
    <FormGrid minColumn="18rem">
      {definitions.map((def) => {
        const label = def.required ? `${def.name} *` : def.name;
        const value = (values[def.id] as string) ?? "";
        if (def.field_type === "long_text") {
          return (
            <FormGridFull key={def.id}>
              <TextAreaField helpNotNeeded label={label} rows={3} disabled={disabled} value={value} onChange={(next) => onChange(def.id, next)} />
            </FormGridFull>
          );
        }
        if (def.field_type === "checkbox") {
          return (
            <CheckboxField helpNotNeeded
              key={def.id} label={label} disabled={disabled}
              checked={Boolean(values[def.id])} onChange={(next) => onChange(def.id, next)}
            />
          );
        }
        if (def.field_type === "list") {
          return (
            <LabeledSelect helpNotNeeded
              key={def.id} label={label} disabled={disabled} value={value} onChange={(next) => onChange(def.id, next)}
              options={(def.options ?? []).map((opt) => ({ value: String(opt), label: String(opt) }))}
            />
          );
        }
        return <TextField helpNotNeeded key={def.id} label={label} disabled={disabled} value={value} onChange={(next) => onChange(def.id, next)} />;
      })}
    </FormGrid>
  );
}
