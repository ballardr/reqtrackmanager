/**
 * Module: components/ScoringLevelPicker
 *
 * Picks one level of a scoring axis (generic scoring-matrix core)
 * — e.g. a Pain Point's Severity for one persona. A labelled
 * select (shared `LabeledSelect`) with an explicit "Not scored" option,
 * because an unset input means "not scored under models that use this
 * axis", never zero. The field's `(?)` help tooltip lists every level with its
 * guidance, so scorers apply the scale consistently and can compare levels
 * before choosing, without a note taking a row once they know the scale. The
 * help text does not depend on the selection, so choosing a level never swaps
 * the field's markup and drops the select's focus.
 */
import type { ScoringAxis } from "../api/scoring";
import { LabeledSelect } from "./LabeledSelect";

/** One line per level, "Name: guidance" (just the name for a level with none); undefined when no level has guidance. */
function levelGuide(axis: ScoringAxis): string | undefined {
  if (!axis.levels.some((l) => l.description)) return undefined;
  return axis.levels.map((l) => (l.description ? `${l.name}: ${l.description}` : l.name)).join("\n");
}

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
  return (
    <LabeledSelect
      label={axis.label}
      help={levelGuide(axis)}
      value={value ?? ""}
      onChange={(next) => onChange(next || null)}
      options={axis.levels.map((l) => ({ value: l.id, label: l.name }))}
      disabled={disabled}
      placeholder="Not scored"
    />
  );
}
