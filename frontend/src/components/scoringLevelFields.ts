/**
 * Module: components/scoringLevelFields
 *
 * The level rows of the scoring editors (`ScoringAxisLevels`, used by the organisation `ScoringSchemeEditor` and the project
 * `ProjectScoringSettings`): the editable fields of one level, and the parse of a row's text into the API body. A derived axis (Demand) adds a
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

/** The editable fields of one level row, as the columns of a `DefinitionList` grid; a derived axis adds the threshold. */
export function levelFields(axis: ScoringAxis): DefinitionListField<ScoringLevel>[] {
  const fields: DefinitionListField<ScoringLevel>[] = [
    {
      key: "name", getValue: (l: ScoringLevel) => l.name, label: "Level", placeholder: "Level name",
      ariaLabel: `${axis.label} level name`, track: "minmax(10rem, 1.5fr)",
    },
    {
      key: "weight", getValue: (l: ScoringLevel) => String(l.weight), label: "Weight", placeholder: "Weight",
      ariaLabel: `${axis.label} level weight`, track: "6.5rem", inputType: "number",
    },
  ];
  if (axis.derived_source) {
    fields.push({
      key: "threshold", getValue: (l: ScoringLevel) => (l.threshold == null ? "" : String(l.threshold)), label: "From",
      placeholder: "From", ariaLabel: `${axis.label} level threshold`, track: "6.5rem", inputType: "number",
    });
  }
  return [...fields, {
    key: "description", getValue: (l: ScoringLevel) => l.description ?? "", label: "Guidance", placeholder: "Guidance",
    ariaLabel: `${axis.label} level guidance`, track: "minmax(12rem, 3fr)", optional: true, multiline: true,
  }];
}
