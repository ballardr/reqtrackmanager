/**
 * Module: components/ScoringModelBands
 *
 * The "rating bands per model" block shared by the org-level
 * `ScoringSchemeEditor` and project-level `ProjectScoringSettings`
 * (generic scoring-matrix core, Module 1 Phase 10): pick a model, edit its
 * bands (`ScoringBandsEditor`), and preview them on the model's first two
 * axes (`ScoringMatrixChart`; first axis = rows, second = columns). Only *where* bands are saved differs between
 * the two callers, so that is all they pass in.
 */
import { useState } from "react";

import { SCORING_SOURCE_LABEL, type ScoringBand, type ScoringModel, type ScoringScheme } from "../api/scoring";
import { LabeledSelect } from "./LabeledSelect";
import { ScoringBandsEditor } from "./ScoringBandsEditor";
import { ScoringMatrixChart } from "./ScoringMatrixChart";

/**
 * @param scheme The effective scheme configuration.
 * @param isCustom Whether a model's bands are this level's own override.
 * @param resetLabel Text of the reset action.
 * @param onSave Saves a model's bands (caller owns feedback; must not throw).
 * @param onReset Clears a model's override (same contract).
 */
export function ScoringModelBands({
  scheme, isCustom, resetLabel, onSave, onReset,
}: {
  scheme: ScoringScheme;
  isCustom: (model: ScoringModel) => boolean;
  resetLabel?: string;
  onSave: (modelKey: string, bands: ScoringBand[]) => Promise<void>;
  onReset: (modelKey: string) => Promise<void>;
}) {
  const [modelKey, setModelKey] = useState(scheme.default_model_key);
  const model = scheme.models.find((m) => m.key === modelKey) ?? scheme.models[0];
  // First axis on the rows (Y), second across the columns (X).
  const [yKey, xKey] = model.axis_keys;
  const xAxis = scheme.axes.find((a) => a.key === xKey);
  const yAxis = scheme.axes.find((a) => a.key === yKey);
  return (
    <div className="stack">
      <LabeledSelect label="Model" value={model.key} onChange={setModelKey} placeholder={null}
        options={scheme.models.map((m) => ({ value: m.key, label: m.label }))} />
      <p className="text-muted" style={{ margin: 0 }}>
        Bands are based on the score as a percentage of the model's maximum, so they still apply if level weights change.
      </p>
      <ScoringBandsEditor
        bands={model.bands}
        custom={isCustom(model)}
        defaultLabel={SCORING_SOURCE_LABEL[model.bands_source]}
        resetLabel={resetLabel}
        onSave={(bands) => onSave(model.key, bands)}
        onReset={() => onReset(model.key)}
      />
      {xAxis && yAxis && (
        <ScoringMatrixChart
          xAxis={xAxis} yAxis={yAxis} bands={model.bands}
          caption={
            model.axis_keys.length > 2
              ? `Preview at the top level of the remaining axes (${model.label}).`
              : `Preview (${model.label}).`
          }
        />
      )}
    </div>
  );
}
