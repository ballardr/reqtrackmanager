/**
 * Module: components/LineShapeSelect
 *
 * The one choice of a line's shape (Straight, Curved or Spline), shared by a canvas editor's settings (the diagram's default
 * shape) and a Selection card (one line's own shape, which may follow the default).
 *
 * Responsibilities:
 * - List the three shapes by their label map, and for one line a leading "Diagram default (X)" entry naming what the line follows.
 * - Say what each option means in the caption's help, one line per option.
 *
 * Design decisions:
 * - Nothing is stored here: the editor page owns the value and the save.
 * - The label map is keyed by the shape type, so a fourth shape cannot be added without its label.
 */
import { useStrings } from "../context/TerminologyContext";
import { labelOptions } from "../utils/labelOptions";
import { LabeledSelect } from "./LabeledSelect";
import { LINE_SHAPES, type LineShape } from "./graphLinePath";

/**
 * @param value The shape chosen, or null for a line that follows its diagram's default (only for `fallback` given).
 * @param onChange Called with the new shape, or null when the line is set back to the diagram's default.
 * @param fallback The diagram's default shape: given, the select leads with "Diagram default (X)" and null is a value; left out, the select is the default itself.
 * @param disabled True when the choice cannot be changed.
 */
export function LineShapeSelect({
  value, onChange, fallback, disabled,
}: {
  value: LineShape | null;
  onChange: (next: LineShape | null) => void;
  fallback?: LineShape;
  disabled?: boolean;
}) {
  const text = useStrings().graphCanvas;
  const labels = text.lineShapeNames;
  const options = [
    ...(fallback ? [{ value: "", label: text.lineShapeFollowing(labels[fallback]) }] : []),
    ...labelOptions(labels),
  ];
  return (
    <LabeledSelect
      label={fallback ? text.lineShapeLabel : text.lineShapeDefaultLabel}
      help={fallback ? text.lineShapeOwnHelp : text.lineShapeDefaultHelp}
      placeholder={null} disabled={disabled} value={value ?? ""} options={options}
      onChange={(next) => onChange(LINE_SHAPES.find((s) => s === next) ?? null)}
    />
  );
}
