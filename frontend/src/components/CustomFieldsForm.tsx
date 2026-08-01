import type { CustomFieldDefinition } from "../api/types";

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
    <div className="stack">
      {definitions.map((def) => (
        <label key={def.id} className="stack" style={{ gap: "0.25rem" }}>
          {def.name}
          {def.required && " *"}
          {def.field_type === "short_text" && (
            <input
              className="input"
              disabled={disabled}
              value={(values[def.id] as string) ?? ""}
              onChange={(e) => onChange(def.id, e.target.value)}
            />
          )}
          {def.field_type === "long_text" && (
            <textarea
              className="input"
              rows={3}
              disabled={disabled}
              value={(values[def.id] as string) ?? ""}
              onChange={(e) => onChange(def.id, e.target.value)}
            />
          )}
          {def.field_type === "checkbox" && (
            <input
              type="checkbox"
              disabled={disabled}
              checked={Boolean(values[def.id])}
              onChange={(e) => onChange(def.id, e.target.checked)}
            />
          )}
          {def.field_type === "list" && (
            <select
              className="input"
              disabled={disabled}
              value={(values[def.id] as string) ?? ""}
              onChange={(e) => onChange(def.id, e.target.value)}
            >
              <option value="" disabled>
                Select…
              </option>
              {(def.options ?? []).map((opt) => (
                <option key={String(opt)} value={String(opt)}>
                  {String(opt)}
                </option>
              ))}
            </select>
          )}
        </label>
      ))}
    </div>
  );
}
