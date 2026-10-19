/**
 * Module: components/ScoringModelSwitcher
 *
 * The "chosen when viewing" control of the generic scoring-matrix core:
 * picks which scoring model ranks a
 * view and, optionally, how per-persona scores roll up. Both are plain
 * `LabeledSelect`s without a blank option — a view is always under exactly
 * one model. The caller passes the effective default model as the initial
 * value and owns any persistence (none, for a per-view choice).
 */
import { LabeledSelect } from "./LabeledSelect";
import { useStrings } from "../context/TerminologyContext";

export interface ScoringOption {
  value: string;
  label: string;
}

/**
 * @param models Selectable models (key + label).
 * @param model The selected model key.
 * @param onModelChange Called with the newly selected model key.
 * @param rollups Optional roll-up choices; omitted hides the roll-up select.
 * @param rollup The selected roll-up key (required when `rollups` is given).
 * @param onRollupChange Called with the newly selected roll-up key.
 */
export function ScoringModelSwitcher({
  models, model, onModelChange, rollups, rollup, onRollupChange,
}: {
  models: ScoringOption[];
  model: string;
  onModelChange: (model: string) => void;
  rollups?: ScoringOption[];
  rollup?: string;
  onRollupChange?: (rollup: string) => void;
}) {
  const strings = useStrings();
  return (
    <div className="row" style={{ gap: "1rem", flexWrap: "wrap", alignItems: "flex-end" }}>
      <LabeledSelect help={strings.help.scoringModel} label="Scoring model" value={model} onChange={onModelChange} options={models} placeholder={null} />
      {rollups && rollup !== undefined && onRollupChange && (
        <LabeledSelect help={strings.help.scoringRollup} label="Combine personas by" value={rollup} onChange={onRollupChange} options={rollups} placeholder={null} />
      )}
    </div>
  );
}
