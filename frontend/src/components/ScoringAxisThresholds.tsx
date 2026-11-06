/**
 * Module: components/ScoringAxisThresholds
 *
 * A project's thresholds for one derived axis (Demand): where each level starts in this project, beside the
 * organisation's own. The level names and weights are the organisation's and shown read-only; only the "From" column
 * is editable. A project either keeps the inherited values or sets its own for every level (a set, so the
 * thresholds can never fall out of order); `OverridePill` says which and offers the way back.
 *
 * The caller owns the saving and its feedback (toast); this component only holds the draft and validates it the way
 * the server does (every level filled, none negative, each above the one before).
 */
import { useState } from "react";

import { type ScoringAxis } from "../api/scoring";
import { t } from "../i18n/strings";
import { FieldCaption } from "./FieldHelp";
import { InlineTextInput } from "./FormFields";
import { OverridePill } from "./OverridePill";

const strings = t();

const SOURCE_LABEL = {
  organisation: "Organisation values",
  ancestor: "Inherited from parent project",
  project: "Set on this project",
} as const;

/** The draft as text by level id, from the thresholds in force. */
const toDraft = (axis: ScoringAxis): Record<string, string> =>
  Object.fromEntries(axis.levels.map((l) => [l.id, l.threshold == null ? "" : String(l.threshold)]));

/** What is wrong with a draft, or null: every level filled, none negative, rising with the levels' weights. */
function validate(axis: ScoringAxis, draft: Record<string, string>): string | null {
  const values = axis.levels.map((l) => draft[l.id]?.trim() ?? "");
  if (values.some((v) => v === "" || !Number.isFinite(Number(v)) || Number(v) < 0)) return "Give every level a threshold of zero or more.";
  const numbers = values.map(Number);
  if (numbers.some((n, i) => i > 0 && n <= numbers[i - 1])) return "Each level must start above the one before.";
  return null;
}

/**
 * @param axis The derived axis as the project sees it (its `thresholds_source` and each level's `threshold` in force and `org_threshold`).
 * @param onSave Persists the project's thresholds by level id.
 * @param onReset Clears the project's own thresholds so it inherits.
 */
export function ScoringAxisThresholds({
  axis, onSave, onReset,
}: {
  axis: ScoringAxis;
  onSave: (thresholds: Record<string, number>) => Promise<void>;
  onReset: () => Promise<void>;
}) {
  const [draft, setDraft] = useState(() => toDraft(axis));
  const [busy, setBusy] = useState(false);
  // Re-seed the draft when the saved thresholds change (after a save or reset): adjust state during render, not an effect.
  const [saved, setSaved] = useState(axis.levels);
  if (axis.levels !== saved) {
    setSaved(axis.levels);
    setDraft(toDraft(axis));
  }
  const source = axis.thresholds_source ?? "organisation";
  const error = validate(axis, draft);
  const dirty = JSON.stringify(draft) !== JSON.stringify(toDraft(axis));

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
        <FieldCaption label="Thresholds" help={strings.help.scoringThresholds} />
        <OverridePill
          custom={source === "project"} defaultLabel={SOURCE_LABEL[source === "project" ? "organisation" : source]}
          resetLabel="Use inherited values" onReset={() => void run(onReset)} disabled={busy}
        />
      </div>
      <div className="definition-grid" style={{ gridTemplateColumns: "minmax(10rem, 1.5fr) 6.5rem 8rem 10rem minmax(12rem, 3fr)" }}>
        <span className="definition-grid__head">Level</span>
        <span className="definition-grid__head">Weight</span>
        <span className="definition-grid__head">Organisation</span>
        <span className="definition-grid__head">From (this project)</span>
        <span className="definition-grid__head">Guidance</span>
        {axis.levels.map((level) => (
          <div key={level.id} style={{ display: "contents" }}>
            <span className="definition-grid__cell">{level.name}</span>
            <span className="definition-grid__cell">{level.weight}</span>
            <span className="definition-grid__cell text-muted">{level.org_threshold ?? ""}</span>
            <div className="definition-grid__cell">
              <InlineTextInput
                type="number" ariaLabel={`${axis.label} ${level.name} threshold in this project`} value={draft[level.id] ?? ""}
                onChange={(value) => setDraft((d) => ({ ...d, [level.id]: value }))}
              />
            </div>
            <span className="definition-grid__cell text-muted">{level.description ?? ""}</span>
          </div>
        ))}
      </div>
      {error && dirty && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
      <div className="row" style={{ gap: "var(--space-3)" }}>
        <button
          type="button" className="btn btn-primary" disabled={!dirty || !!error || busy}
          onClick={() => void run(() => onSave(Object.fromEntries(axis.levels.map((l) => [l.id, Number(draft[l.id])]))))}
        >
          Save thresholds
        </button>
      </div>
    </div>
  );
}
