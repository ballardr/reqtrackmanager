/**
 * Module: components/ScoringLevelPicker
 *
 * Picks one level of a scoring axis (generic scoring-matrix core, Module 1
 * Phase 10) — e.g. a Pain Point's Severity for one persona. A labelled
 * select (shared `LabeledSelect`) with an explicit "Not scored" option,
 * because an unset input means "not scored under models that use this
 * axis", never zero. The chosen level's guidance text shows underneath so
 * scorers apply levels consistently.
 */
import type { ScoringAxis } from "../api/scoring";
import { LabeledSelect } from "./LabeledSelect";

/**
 * @param axis The axis whose org-configured levels are offered.
 * @param value The selected level id, or null for "Not scored".
 * @param onChange Called with the new level id, or null when cleared.
 * @param disabled Disables the control.
 */
export function ScoringLevelPicker({
  axis, value, onChange, disabled,
}: {
  axis: ScoringAxis;
  value: string | null;
  onChange: (levelId: string | null) => void;
  disabled?: boolean;
}) {
  const selected = axis.levels.find((l) => l.id === value) ?? null;
  return (
    <div className="stack" style={{ gap: "0.25rem" }}>
      <LabeledSelect
        label={axis.label}
        value={value ?? ""}
        onChange={(next) => onChange(next || null)}
        options={axis.levels.map((l) => ({ value: l.id, label: l.name }))}
        disabled={disabled}
        placeholder="Not scored"
      />
      {selected?.description && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{selected.description}</span>}
    </div>
  );
}
