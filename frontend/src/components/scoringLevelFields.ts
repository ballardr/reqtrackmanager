/**
 * Module: components/scoringLevelFields
 *
 * The level rows of the scoring editors (organisation `ScoringSchemeEditor`, project `ProjectScoringSettings`): the
 * editable fields of one level, and the parse of a row's text into the API body. A derived axis (Demand) adds a
 * threshold field, which the server requires on it and refuses on a manual axis.
 */
import type { ScoringAxis, ScoringLevel } from "../api/scoring";
import type { DefinitionListField } from "./DefinitionList";

/** The level a row describes; a derived axis's level also carries the threshold its value must reach. */
export function parseLevel(values: Record<string, string>, derived = false) {
  const weight = Number(values.weight);
  if (!Number.isFinite(weight) || weight <= 0) throw new Error("Weight must be a positive number.");
  const level = { name: values.name.trim(), weight, description: values.description.trim() || null };
  if (!derived) return level;
  const threshold = Number(values.threshold);
  if (values.threshold.trim() === "" || !Number.isFinite(threshold) || threshold < 0) {
    throw new Error("Threshold must be zero or more.");
  }
  return { ...level, threshold };
}

/** The editable fields of one level row; a derived axis adds the threshold. */
export function levelFields(axis: ScoringAxis): DefinitionListField<ScoringLevel>[] {
  const fields: DefinitionListField<ScoringLevel>[] = [
    { key: "name", getValue: (l: ScoringLevel) => l.name, placeholder: "Level name", ariaLabel: `${axis.label} level name`, maxWidth: 180 },
    { key: "weight", getValue: (l: ScoringLevel) => String(l.weight), placeholder: "Weight", ariaLabel: `${axis.label} level weight`, maxWidth: 90, inputType: "number" },
  ];
  if (axis.derived_source) {
    fields.push({
      key: "threshold", getValue: (l: ScoringLevel) => (l.threshold == null ? "" : String(l.threshold)), placeholder: "From",
      ariaLabel: `${axis.label} level threshold`, maxWidth: 90, inputType: "number",
    });
  }
  return [...fields, { key: "description", getValue: (l: ScoringLevel) => l.description ?? "", placeholder: "Guidance", ariaLabel: `${axis.label} level guidance`, maxWidth: 360, optional: true }];
}
