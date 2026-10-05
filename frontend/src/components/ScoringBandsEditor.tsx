/**
 * Module: components/ScoringBandsEditor
 *
 * Edits one scoring model's rating bands (generic scoring-matrix core,
 * Module 1 Phase 10) at org or project level. A band is a label, a lower
 * threshold (entered as a percentage of the model's maximum score) and a
 * tone from the shared `BadgeTone` palette. Client-side validation mirrors
 * the backend's `validate_scoring_bands` so mistakes show before saving.
 *
 * Override visibility follows the style guide's "platform default vs.
 * override" pattern via `OverridePill`: the caller says whether the bands
 * shown are this level's own (`custom`) and what they otherwise inherit
 * from (`defaultLabel`); resetting clears the override.
 */
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { SCORING_BAND_TONE_LABEL, type ScoringBand } from "../api/scoring";
import type { BadgeTone } from "../api/types";
import { OverridePill } from "./OverridePill";

interface DraftBand {
  label: string;
  percent: string;
  tone: BadgeTone;
}

const TONES = Object.keys(SCORING_BAND_TONE_LABEL) as BadgeTone[];
const MAX_BANDS = 10;

function toDraft(bands: ScoringBand[]): DraftBand[] {
  return bands.map((b) => ({ label: b.label, percent: String(Math.round(b.min_score * 1000) / 10), tone: b.tone }));
}

/** Returns a validation message for the draft, or null if it is valid. */
function validateBandDraft(draft: { label: string; percent: string }[]): string | null {
  if (draft.length === 0 || draft.length > MAX_BANDS) return `Define between 1 and ${MAX_BANDS} bands.`;
  const labels = new Set<string>();
  let previous = -1;
  for (const [i, band] of draft.entries()) {
    const label = band.label.trim().toLowerCase();
    if (!label) return "Every band needs a label.";
    if (labels.has(label)) return `Duplicate band label "${band.label}".`;
    labels.add(label);
    const percent = Number(band.percent);
    if (band.percent.trim() === "" || Number.isNaN(percent)) return "Every band needs a starting percentage.";
    if (i === 0 && percent !== 0) return "The first band must start at 0%.";
    if (percent < 0 || percent >= 100 || percent <= previous) return "Starting percentages must increase and stay below 100%.";
    previous = percent;
  }
  return null;
}

/**
 * @param bands The currently effective bands.
 * @param custom Whether `bands` are this level's own override.
 * @param defaultLabel What non-custom bands are inherited from.
 * @param resetLabel Text of the reset action.
 * @param onSave Persists a new band set. The caller owns feedback (toast on
 *   success and failure) and must not let errors escape.
 * @param onReset Clears the override; same feedback contract as `onSave`.
 */
export function ScoringBandsEditor({
  bands, custom, defaultLabel, resetLabel, onSave, onReset,
}: {
  bands: ScoringBand[];
  custom: boolean;
  defaultLabel: string;
  resetLabel?: string;
  onSave: (bands: ScoringBand[]) => Promise<void>;
  onReset: () => Promise<void>;
}) {
  const [draft, setDraft] = useState<DraftBand[]>(() => toDraft(bands));
  const [busy, setBusy] = useState(false);
  // Reset the draft when the saved bands change (e.g. after save/reset or a
  // model switch) — React's "adjust state during render" pattern rather than
  // an effect, so the stale draft never renders.
  const [savedBands, setSavedBands] = useState(bands);
  if (bands !== savedBands) {
    setSavedBands(bands);
    setDraft(toDraft(bands));
  }

  const error = validateBandDraft(draft);
  const dirty = JSON.stringify(draft) !== JSON.stringify(toDraft(bands));
  const update = (i: number, patch: Partial<DraftBand>) =>
    setDraft((d) => d.map((band, j) => (j === i ? { ...band, ...patch } : band)));

  async function run(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ gap: "0.5rem" }}>
      <div className="row" style={{ gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
        <span>Rating bands</span>
        <OverridePill custom={custom} defaultLabel={defaultLabel} resetLabel={resetLabel}
          onReset={() => void run(onReset)} disabled={busy} />
      </div>
      {draft.map((band, i) => (
        <div key={i} className="row" style={{ gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
          <input className="input" style={{ maxWidth: 160 }} aria-label={`Band ${i + 1} label`} value={band.label}
            onChange={(e) => update(i, { label: e.target.value })} />
          <label className="row" style={{ gap: "0.25rem", alignItems: "center" }}>
            <span className="text-muted">from</span>
            <input className="input" type="number" min={0} max={99.9} step={0.1} style={{ maxWidth: 90 }}
              aria-label={`Band ${i + 1} starts at percent`} value={band.percent} disabled={i === 0}
              onChange={(e) => update(i, { percent: e.target.value })} />
            <span className="text-muted">%</span>
          </label>
          <select className="input" style={{ maxWidth: 120 }} aria-label={`Band ${i + 1} colour`} value={band.tone}
            onChange={(e) => update(i, { tone: e.target.value as BadgeTone })}>
            {TONES.map((tone) => <option key={tone} value={tone}>{SCORING_BAND_TONE_LABEL[tone]}</option>)}
          </select>
          <span className={`badge badge--${band.tone}`}>{band.label || "—"}</span>
          <button type="button" className="btn btn-danger" aria-label={`Remove band ${i + 1}`} title="Remove band"
            disabled={draft.length <= 1} onClick={() => setDraft((d) => d.filter((_, j) => j !== i))}>
            <Trash2 size={14} />
          </button>
        </div>
      ))}
      {error && dirty && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
      <div className="row" style={{ gap: "0.5rem" }}>
        <button type="button" className="btn" disabled={draft.length >= MAX_BANDS}
          onClick={() => setDraft((d) => [...d, { label: "", percent: d.length ? "" : "0", tone: "muted" }])}>
          <Plus size={14} /> Add band
        </button>
        <button type="button" className="btn btn-primary" disabled={!dirty || !!error || busy}
          onClick={() => void run(() => onSave(draft.map((b) => ({ label: b.label.trim(), min_score: Number(b.percent) / 100, tone: b.tone }))))}>
          Save bands
        </button>
      </div>
    </div>
  );
}
