/**
 * Module: components/ScoringModelBands
 *
 * The "rating bands per model" block shared by the org-level
 * `ScoringSchemeEditor` and project-level `ProjectScoringSettings`
 * (generic scoring-matrix core): pick a model, edit its
 * bands (`ScoringBandsEditor`), and preview them on the model's first two
 * axes (`ScoringMatrixChart`; first axis = rows, second = columns). For a
 * two-axis model the preview becomes the cell-ratings editor
 * (`ScoringCellRatingsEditor`) when the caller supplies the cell handlers.
 * Only *where* bands and cell ratings are saved differs between the two
 * callers, so that is all they pass in.
 */
import { useState } from "react";

import {
  SCORING_SOURCE_LABEL, type ScoringBand, type ScoringCellRating, type ScoringModel, type ScoringScheme,
} from "../api/scoring";
import { LabeledSelect } from "./LabeledSelect";
import { ScoringCellRatingsEditor } from "./ScoringCellRatingsEditor";
import { ScoringBandsEditor } from "./ScoringBandsEditor";
import { ScoringMatrixChart } from "./ScoringMatrixChart";

/**
 * @param scheme The effective scheme configuration.
 * @param isCustom Whether a model's bands are this level's own override.
 * @param resetLabel Text of the reset action.
 * @param onSave Saves a model's bands (caller owns feedback; must not throw).
 * @param onReset Clears a model's override (same contract).
 * @param isCellsCustom Whether a model's cell ratings are this level's own override.
 * @param onSaveCells Saves a two-axis model's cell ratings (same feedback contract).
 * @param onResetCells Clears a model's cell-rating override.
 */
export function ScoringModelBands({
  scheme, isCustom, resetLabel, onSave, onReset, isCellsCustom, onSaveCells, onResetCells,
}: {
  scheme: ScoringScheme;
  isCustom: (model: ScoringModel) => boolean;
  resetLabel?: string;
  onSave: (modelKey: string, bands: ScoringBand[]) => Promise<void>;
  onReset: (modelKey: string) => Promise<void>;
  isCellsCustom?: (model: ScoringModel) => boolean;
  onSaveCells?: (modelKey: string, cells: ScoringCellRating[]) => Promise<void>;
  onResetCells?: (modelKey: string) => Promise<void>;
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
      {xAxis && yAxis && model.axis_keys.length === 2 && onSaveCells && onResetCells && isCellsCustom ? (
        <ScoringCellRatingsEditor
          xAxis={xAxis} yAxis={yAxis} bands={model.bands} cellRatings={model.cell_ratings}
          custom={isCellsCustom(model)} defaultLabel={SCORING_SOURCE_LABEL[model.cell_ratings_source]}
          resetLabel={resetLabel} caption={`Preview (${model.label}).`}
          onSave={(cells) => onSaveCells(model.key, cells)} onReset={() => onResetCells(model.key)}
        />
      ) : xAxis && yAxis && (
        <ScoringMatrixChart
          xAxis={xAxis} yAxis={yAxis} bands={model.bands} cellRatings={model.cell_ratings}
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
