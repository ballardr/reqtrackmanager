/**
 * Module: components/ScoringCellRatingsEditor
 *
 * Edits one two-axis scoring model's explicit per-cell ratings (generic
 * scoring-matrix core) at org or project level: the
 * matrix itself (`ScoringMatrixChart` in edit mode) with a band picker in
 * each cell. A pinned cell overrides the threshold bands for that cell only,
 * which is what lets a matrix be non-monotonic in the product of its levels'
 * weights. A cell left on "Thresholds" keeps the band its score earns.
 *
 * Edits are batched behind one Save (like `ScoringBandsEditor`); override
 * visibility follows the style guide's "platform default vs. override"
 * pattern via `OverridePill`. Cells can only use bands that are already
 * saved, so band edits are saved first.
 */
import { useState } from "react";

import type { ScoringAxis, ScoringBand, ScoringCellRating } from "../api/scoring";
import { OverridePill } from "./OverridePill";
import { ScoringMatrixChart } from "./ScoringMatrixChart";

const sameCell = (a: ScoringCellRating, firstId: string, secondId: string) =>
  a.first_level_id === firstId && a.second_level_id === secondId;

/**
 * @param xAxis Column axis (the model's second axis).
 * @param yAxis Row axis (the model's first axis).
 * @param bands The model's effective bands (the options a cell can pin to).
 * @param cellRatings The currently effective cell ratings.
 * @param custom Whether `cellRatings` are this level's own override.
 * @param defaultLabel What non-custom ratings are inherited from.
 * @param resetLabel Text of the reset action.
 * @param caption Accessible table caption.
 * @param onSave Persists a new set. The caller owns feedback (toast on
 *   success and failure) and must not let errors escape.
 * @param onReset Clears the override; same feedback contract as `onSave`.
 */
export function ScoringCellRatingsEditor({
  xAxis, yAxis, bands, cellRatings, custom, defaultLabel, resetLabel, caption, onSave, onReset,
}: {
  xAxis: ScoringAxis;
  yAxis: ScoringAxis;
  bands: ScoringBand[];
  cellRatings: ScoringCellRating[];
  custom: boolean;
  defaultLabel: string;
  resetLabel?: string;
  caption: string;
  onSave: (cells: ScoringCellRating[]) => Promise<void>;
  onReset: () => Promise<void>;
}) {
  const [draft, setDraft] = useState<ScoringCellRating[]>(cellRatings);
  const [busy, setBusy] = useState(false);
  // Re-seed the draft when the saved set changes (save, reset or model
  // switch): "adjust state during render" so a stale draft never renders.
  const [saved, setSaved] = useState(cellRatings);
  if (cellRatings !== saved) {
    setSaved(cellRatings);
    setDraft(cellRatings);
  }
  const dirty = JSON.stringify(draft) !== JSON.stringify(cellRatings);

  function change(firstId: string, secondId: string, label: string | null) {
    setDraft((d) => {
      const rest = d.filter((c) => !sameCell(c, firstId, secondId));
      return label === null ? rest : [...rest, { first_level_id: firstId, second_level_id: secondId, band_label: label }];
    });
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ gap: "var(--space-3)" }}>
      <div className="row" style={{ gap: "var(--space-3)", alignItems: "center", flexWrap: "wrap" }}>
        <span>Cell ratings</span>
        <OverridePill custom={custom} defaultLabel={defaultLabel} resetLabel={resetLabel}
          onReset={() => void run(onReset)} disabled={busy} />
      </div>
      <p className="text-muted" style={{ margin: 0 }}>
        Pin a cell to a band to override its threshold band; cells left on Thresholds keep the band their score earns.
      </p>
      <ScoringMatrixChart xAxis={xAxis} yAxis={yAxis} bands={bands} cellRatings={draft}
        onCellRatingChange={change} caption={caption} />
      <div className="row" style={{ gap: "var(--space-3)" }}>
        <button type="button" className="btn btn-primary" disabled={!dirty || busy}
          onClick={() => void run(() => onSave(draft))}>
          Save cell ratings
        </button>
        <button type="button" className="btn" disabled={!dirty || busy} onClick={() => setDraft(cellRatings)}>
          Discard changes
        </button>
      </div>
    </div>
  );
}
