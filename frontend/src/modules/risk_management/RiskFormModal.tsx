/**
 * Module: modules/risk_management/RiskFormModal
 *
 * Create/edit dialog for a risk's content fields, shared by the register
 * (create) and the detail page (edit) and told apart by whether `initial` is
 * passed — the convention `DecisionFormModal` uses. Inherent and residual
 * Likelihood/Consequence/Detectability levels are picked with the shared
 * `ScoringLevelPicker`, so the level names and guidance come from the project's
 * configured scheme; the rating itself is derived by the backend and never
 * entered here.
 *
 * On an Accepted risk the backend locks the levels, treatment strategy and
 * acceptance criteria (move it back to Assessed to change them), so those
 * controls are disabled with an explanation instead of failing on save. Edit
 * mode asks for an optional change note, stored on the new version.
 */
import { useState } from "react";

import type { ScoringScheme } from "../../api/scoring";
import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { ScoringLevelPicker } from "../../components/ScoringLevelPicker";
import { blankRiskValues, valuesFromRisk } from "./riskFields";
import { CONSEQUENCE_AXIS, DETECTABILITY_AXIS, findAxis, LIKELIHOOD_AXIS } from "./useRiskScheme";
import { TREATMENT_STRATEGY_LABEL } from "./types";
import type { Risk, RiskFieldValues, TreatmentStrategy } from "./types";

type LevelKey = Extract<keyof RiskFieldValues, `${"inherent" | "residual"}_${string}_level_id`>;

const AXES = [
  { axis: LIKELIHOOD_AXIS, suffix: "likelihood" },
  { axis: CONSEQUENCE_AXIS, suffix: "consequence" },
  { axis: DETECTABILITY_AXIS, suffix: "detectability" },
] as const;

/**
 * @param initial The risk being edited; omit to create.
 * @param scheme The project's effective `risk` scheme (null while loading: the level pickers are omitted).
 * @param riskTypes The enabled project risk types.
 * @param userOptions Org users offered as owner.
 * @param currentUserId Default owner for a new risk.
 * @param error A save error to show.
 * @param onSave Called with the form values and the change note (edit mode only).
 */
export function RiskFormModal({
  initial, scheme, riskTypes, userOptions, currentUserId, error, onCancel, onSave,
}: {
  initial?: Risk;
  scheme: ScoringScheme | null;
  riskTypes: { id: string; name: string }[];
  userOptions: { id: string; display_name: string }[];
  currentUserId?: string;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: RiskFieldValues, changeNote: string) => void;
}) {
  const [values, setValues] = useState<RiskFieldValues>(() =>
    initial ? valuesFromRisk(initial) : blankRiskValues(currentUserId ?? null));
  const [changeNote, setChangeNote] = useState("");
  const set = <K extends keyof RiskFieldValues>(key: K, value: RiskFieldValues[K]) =>
    setValues((prev) => ({ ...prev, [key]: value }));

  const locked = initial?.status === "accepted";
  const valid = values.title.trim() !== "";

  function textField(key: "statement" | "cause" | "risk_event" | "consequence" | "acceptance_criteria", label: string, disabled = false) {
    return (
      <label className="stack" style={{ gap: "0.25rem" }}>
        <span>{label}</span>
        <textarea
          className="input" rows={2} aria-label={label} disabled={disabled}
          value={values[key]} onChange={(e) => set(key, e.target.value)}
        />
      </label>
    );
  }

  function levelGroup(basis: "inherent" | "residual", heading: string) {
    return (
      <fieldset className="stack" style={{ border: "none", padding: 0, margin: 0 }}>
        <legend style={{ fontWeight: 600 }}>{heading}</legend>
        <div className="row" style={{ gap: "1rem", flexWrap: "wrap", alignItems: "flex-start" }}>
          {AXES.map(({ axis, suffix }) => {
            const found = findAxis(scheme, axis);
            if (!found) return null;
            const key = `${basis}_${suffix}_level_id` as LevelKey;
            return (
              <ScoringLevelPicker
                key={key}
                axis={{ ...found, label: `${heading} ${found.label.toLowerCase()}` }}
                value={values[key]}
                onChange={(levelId) => set(key, levelId)}
                disabled={locked}
              />
            );
          })}
        </div>
      </fieldset>
    );
  }

  return (
    <Modal title={initial ? `Edit ${initial.unique_code}` : "New risk"} onClose={onCancel} size="lg">
      <div className="stack">
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Risk title</span>
          <input className="input" aria-label="Risk title" value={values.title} onChange={(e) => set("title", e.target.value)} />
        </label>
        {textField("statement", "Risk statement")}
        {textField("cause", "Cause")}
        {textField("risk_event", "Risk event")}
        {textField("consequence", "Consequence")}
        <LabeledSelect
          label="Risk type"
          value={values.risk_type_id ?? ""}
          onChange={(next) => set("risk_type_id", next || null)}
          options={riskTypes.map((t) => ({ value: t.id, label: t.name }))}
          placeholder="No type"
        />
        <LabeledSelect
          label="Owner"
          value={values.owner_id ?? ""}
          onChange={(next) => set("owner_id", next || null)}
          options={userOptions.map((u) => ({ value: u.id, label: u.display_name }))}
          placeholder="Unassigned"
        />
        {levelGroup("inherent", "Inherent")}
        {levelGroup("residual", "Residual")}
        <LabeledSelect
          label="Treatment strategy"
          value={values.treatment_strategy ?? ""}
          onChange={(next) => set("treatment_strategy", (next || null) as TreatmentStrategy | null)}
          options={Object.entries(TREATMENT_STRATEGY_LABEL).map(([value, label]) => ({ value, label }))}
          placeholder="Not decided"
          disabled={locked}
        />
        {textField("acceptance_criteria", "Acceptance criteria", locked)}
        {locked && (
          <p className="text-muted" style={{ margin: 0 }}>
            This risk is Accepted, so its levels, treatment strategy and acceptance criteria are locked. Move it back to
            Assessed to change them.
          </p>
        )}
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Next review date (optional)</span>
          <input
            className="input" type="date" aria-label="Next review date"
            value={values.review_date ?? ""} onChange={(e) => set("review_date", e.target.value || null)}
          />
        </label>
        {initial && (
          <label className="stack" style={{ gap: "0.25rem" }}>
            <span>Change note (optional)</span>
            <input className="input" aria-label="Change note" value={changeNote} onChange={(e) => setChangeNote(e.target.value)} />
          </label>
        )}
        {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button className="btn btn-primary" disabled={!valid} onClick={() => onSave(values, changeNote)}>Save</button>
        </div>
      </div>
    </Modal>
  );
}
