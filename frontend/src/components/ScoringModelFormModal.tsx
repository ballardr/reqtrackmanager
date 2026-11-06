/**
 * Module: components/ScoringModelFormModal
 *
 * The create/edit dialog for a scoring model an organisation or project defines (generic scoring-matrix core): a
 * name, how the axes combine, and how the model uses each axis it can see. A product multiplies or divides by each
 * axis (with an exponent for how strongly it counts); a weighted sum adds each axis by an importance percentage that
 * totals 100, optionally counting a lower level as better. The checks mirror the server's, so the person sees why
 * Save is unavailable; the server still re-checks. Saving is the caller's, which reports a failure through `error`.
 */
import { useState } from "react";

import type { ScoringAxis, ScoringModel, ScoringModelInput } from "../api/scoring";
import { useStrings } from "../context/TerminologyContext";
import { FormActions } from "./FormActions";
import { CheckboxField, TextField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";

type Combination = ScoringModelInput["combination"];
type Role = "none" | "multiply" | "divide" | "sum";

interface AxisDraft {
  role: Role;
  exponent: string;
  importance: string;
  lowerIsBetter: boolean;
}

const COMBINATION_LABEL: Record<Combination, string> = { product: "Product", weighted_sum: "Weighted sum" };
const ROLE_LABEL: Record<Role, string> = { none: "Not used", multiply: "Multiply by", divide: "Divide by", sum: "Add" };
const PRODUCT_ROLES: Role[] = ["none", "multiply", "divide"];
const SUM_ROLES: Role[] = ["none", "sum"];

/** The draft for one axis, read from the model being edited (or blank when defining a new one). */
function draftFor(axis: ScoringAxis, model?: ScoringModel): AxisDraft {
  const blank: AxisDraft = { role: "none", exponent: "1", importance: "", lowerIsBetter: false };
  if (!model) return blank;
  if (model.combination === "weighted_sum") {
    return model.axis_keys.includes(axis.key)
      ? { role: "sum", exponent: "1", importance: String(model.importance?.[axis.key] ?? ""), lowerIsBetter: !!model.inverted_axis_keys?.includes(axis.key) }
      : blank;
  }
  const exponent = String(model.exponents?.[axis.key] ?? 1);
  if (model.axis_keys.includes(axis.key)) return { ...blank, role: "multiply", exponent };
  if (model.divisor_axis_keys?.includes(axis.key)) return { ...blank, role: "divide", exponent };
  return blank;
}

/**
 * The model the drafts describe, or the reason it cannot be saved yet.
 * @returns `{ input }` when valid, else `{ problem }` naming what to fix (empty while the person has not started).
 */
function buildModel(
  label: string, combination: Combination, axes: ScoringAxis[], drafts: Record<string, AxisDraft>,
): { problem: string; input?: ScoringModelInput } {
  const used = axes.filter((a) => drafts[a.key].role !== "none");
  if (!label.trim()) return { problem: "" };
  if (combination === "product" && !used.some((a) => drafts[a.key].role === "multiply")) {
    return { problem: "Multiply by at least one axis." };
  }
  if (combination === "weighted_sum" && used.length === 0) return { problem: "Add at least one axis." };
  const modelAxes: ScoringModelInput["axes"] = [];
  let total = 0;
  for (const axis of used) {
    const d = drafts[axis.key];
    if (combination === "product") {
      const exponent = Number(d.exponent);
      if (!(exponent > 0 && exponent <= 10)) return { problem: `${axis.label}: the exponent must be above 0 and at most 10.` };
      modelAxes.push({ axis_key: axis.key, role: d.role === "divide" ? "divide" : "multiply", exponent });
    } else {
      const importance = Number(d.importance);
      if (!(importance > 0 && importance <= 100)) return { problem: `${axis.label}: the importance must be above 0 and at most 100.` };
      total += importance;
      modelAxes.push({ axis_key: axis.key, role: "sum", importance, lower_is_better: d.lowerIsBetter });
    }
  }
  if (combination === "weighted_sum" && Math.abs(total - 100) > 0.01) return { problem: `Importance totals ${total}%; it must total 100%.` };
  return { problem: "", input: { label: label.trim(), combination, axes: modelAxes } };
}

/**
 * @param initial The model being edited; omit to define a new one.
 * @param axes The axes the tier can see (any may be used).
 * @param error A save error to show beside the actions.
 * @param onCancel Closes the dialog.
 * @param onSave Called with the model to save.
 */
export function ScoringModelFormModal({
  initial, axes, error, onCancel, onSave,
}: {
  initial?: ScoringModel;
  axes: ScoringAxis[];
  error?: string | null;
  onCancel: () => void;
  onSave: (input: ScoringModelInput) => void;
}) {
  const strings = useStrings();
  const [label, setLabel] = useState(initial?.label ?? "");
  const [combination, setCombination] = useState<Combination>(initial?.combination ?? "product");
  const [drafts, setDrafts] = useState<Record<string, AxisDraft>>(() => Object.fromEntries(axes.map((a) => [a.key, draftFor(a, initial)])));

  function changeCombination(next: Combination) {
    setCombination(next);
    // A role belongs to one combination; keep the axes a person picked by mapping them across.
    setDrafts((all) => Object.fromEntries(Object.entries(all).map(([key, d]) => [
      key, { ...d, role: d.role === "none" ? "none" : next === "product" ? "multiply" : "sum" },
    ])));
  }
  const patch = (key: string, change: Partial<AxisDraft>) => setDrafts((all) => ({ ...all, [key]: { ...all[key], ...change } }));

  const built = buildModel(label, combination, axes, drafts);
  const roles = combination === "product" ? PRODUCT_ROLES : SUM_ROLES;

  return (
    <Modal title={initial ? "Edit scoring model" : "Add a scoring model"} onClose={onCancel} size="lg">
      <div className="stack">
        <TextField label="Name" required value={label} onChange={setLabel} help={strings.help.scoringModelName} inputProps={{ maxLength: 100 }} />
        <LabeledSelect
          label="Combination" value={combination} placeholder={null} help={strings.help.scoringModelCombination}
          options={(Object.keys(COMBINATION_LABEL) as Combination[]).map((c) => ({ value: c, label: COMBINATION_LABEL[c] }))}
          onChange={(c) => changeCombination(c as Combination)}
        />
        <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend><strong>Axes</strong></legend>
          {axes.map((axis) => {
            const d = drafts[axis.key];
            return (
              <div key={axis.key} className="row" style={{ gap: "var(--space-4)", alignItems: "flex-end", flexWrap: "wrap" }}>
                <strong style={{ minWidth: "10rem" }}>{axis.label}</strong>
                <LabeledSelect
                  label="Used as" ariaLabel={`${axis.label} role`} value={d.role} placeholder={null} help={strings.help.scoringModelRole}
                  options={roles.map((r) => ({ value: r, label: ROLE_LABEL[r] }))} onChange={(role) => patch(axis.key, { role: role as Role })}
                />
                {combination === "product" && d.role !== "none" && (
                  <TextField
                    label="Exponent" ariaLabel={`${axis.label} exponent`} value={d.exponent} help={strings.help.scoringModelExponent}
                    onChange={(exponent) => patch(axis.key, { exponent })} inputProps={{ type: "number", min: 0.1, max: 10, step: 0.1 }}
                  />
                )}
                {combination === "weighted_sum" && d.role === "sum" && (
                  <>
                    <TextField
                      label="Importance (%)" ariaLabel={`${axis.label} importance`} value={d.importance} help={strings.help.scoringModelImportance}
                      onChange={(importance) => patch(axis.key, { importance })} inputProps={{ type: "number", min: 1, max: 100, step: 1 }}
                    />
                    <CheckboxField
                      label="Lower is better" ariaLabel={`${axis.label} lower is better`} checked={d.lowerIsBetter}
                      help={strings.help.scoringModelLowerBetter} onChange={(lowerIsBetter) => patch(axis.key, { lowerIsBetter })}
                    />
                  </>
                )}
              </div>
            );
          })}
        </fieldset>
        {built.problem && <span className="text-muted" role="status">{built.problem}</span>}
        <FormActions error={error} onCancel={onCancel} saveDisabled={!built.input} onSave={() => built.input && onSave(built.input)} />
      </div>
    </Modal>
  );
}
