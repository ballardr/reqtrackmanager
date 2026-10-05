/**
 * Module: components/LabeledSelect
 *
 * The `<label className="stack"><span>{label}</span><select className="input"
 * ...>` block that `RequirementMappingsModal.tsx`, the old inline "Add
 * compliance link" popover, and the new requirement-link picker's cascading
 * selects all needed byte-for-byte — extracted once a third and fourth
 * occurrence made it a genuine repeated pattern (platform-review-2026-09
 * Phase 7, `CLAUDE.md`'s reuse rule). Purely presentational: one labelled
 * `<select>` with a leading placeholder option and an optional disabled
 * state. Callers own any cascading-reset behaviour (e.g. clearing a child
 * selection when its parent changes) — this component only renders.
 */
export function LabeledSelect({
  label,
  value,
  onChange,
  options,
  disabled,
  placeholder = "Select…",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  disabled?: boolean;
  /** Leading empty option's text; `null` omits it, for a select that
   * always has a value (e.g. a scoring-model switcher). */
  placeholder?: string | null;
}) {
  return (
    <label className="stack" style={{ gap: "0.25rem" }}>
      <span>{label}</span>
      <select
        className="input"
        aria-label={label}
        disabled={disabled}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {placeholder !== null && <option value="">{placeholder}</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
