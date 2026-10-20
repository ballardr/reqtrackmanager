/**
 * Module: modules/context_strategy/PainPointScoreFields
 *
 * The score grid shared by the Pain Point detail page's `PainPointScoringPanel` and the create
 * form: the "all personas together / each persona separately" choice, then one Severity,
 * Frequency and Confidence picker set per row. The page owns the draft (`painPointScoreDraft`)
 * and the buttons; this component only edits it. Saved rows (detail page only) show their score
 * beside the name through `saved`.
 *
 * Personas come from the caller (`available_targets`), so this module never knows the
 * Stakeholders module exists; with none offered, only "all personas" scoring is possible.
 */
import type { ScoringAxis } from "../../api/scoring";
import { Badge } from "../../components/Badge";
import { LabeledSelect } from "../../components/LabeledSelect";
import { ScoringLevelPicker } from "../../components/ScoringLevelPicker";
import { BlockerBadge, PainPointScoreBadge } from "./PainPointScoreBadges";
import {
  EMPTY_SCORE_ROW, SCORE_AXIS_KEYS, SCORE_MODE_OPTIONS, visibleScoreRows,
  type ScoreAxisKey, type ScoreDraft, type ScoreMode, type ScoreRow,
} from "./painPointScoreDraft";
import { PAIN_POINT_SCORE_TARGET_STATUS_LABEL } from "./types";
import type { PainPointScoreEntry } from "./types";
import { CONTEXT_STRATEGY_HELP } from "./help";

/**
 * @param axes The scheme's axes by key.
 * @param personaRows The persona rows on offer (empty when personas are not available).
 * @param mode Whether one row scores all personas or each persona has its own.
 * @param onModeChange Called when the mode select changes.
 * @param draft The draft being edited.
 * @param onDraftChange Called with the next draft after a level changes.
 * @param disabled Disables every control (a locked Pain Point).
 * @param saved Saved rows by key, to show their score beside the name.
 */
export function PainPointScoreFields({
  axes, personaRows, mode, onModeChange, draft, onDraftChange, disabled = false, saved,
}: {
  axes: Record<string, ScoringAxis>;
  personaRows: ScoreRow[];
  mode: ScoreMode;
  onModeChange: (mode: ScoreMode) => void;
  draft: ScoreDraft;
  onDraftChange: (draft: ScoreDraft) => void;
  disabled?: boolean;
  saved?: Map<string, PainPointScoreEntry>;
}) {
  const personasOffered = personaRows.length > 0;
  const rows = visibleScoreRows(mode, personaRows);

  function setLevel(key: string, axis: ScoreAxisKey, levelId: string | null) {
    onDraftChange({ ...draft, [key]: { ...(draft[key] ?? EMPTY_SCORE_ROW), [axis]: levelId } });
  }

  return (
    <>
      {personasOffered || mode === "persona" ? (
        <LabeledSelect help={CONTEXT_STRATEGY_HELP.scoringMode}
          label="Scoring mode" value={mode} onChange={(next) => onModeChange(next as ScoreMode)}
          options={SCORE_MODE_OPTIONS} placeholder={null} disabled={disabled}
        />
      ) : (
        <p className="text-muted" style={{ margin: 0 }}>Personas aren't available in this project, so scores apply to all personas.</p>
      )}

      {rows.map((row) => {
        const savedRow = saved?.get(row.key);
        const values = draft[row.key] ?? EMPTY_SCORE_ROW;
        return (
          <div key={row.key} className="stack" role="group" aria-label={`${row.label} scores`}>
            <div className="row" style={{ gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
              <strong>{row.label}</strong>
              {row.note && <span className="text-muted">{row.note}</span>}
              {row.retired && <Badge tone="muted">{PAIN_POINT_SCORE_TARGET_STATUS_LABEL.inactive}</Badge>}
              {savedRow && <PainPointScoreBadge score={savedRow.score} />}
              {savedRow && <BlockerBadge summary={{ is_blocker: savedRow.is_blocker, blocker_labels: [] }} />}
            </div>
            <div className="row" style={{ gap: "1rem", flexWrap: "wrap", alignItems: "flex-start" }}>
              {SCORE_AXIS_KEYS.map((axisKey) => axes[axisKey] && (
                <ScoringLevelPicker
                  key={axisKey} axis={axes[axisKey]} value={values[axisKey]}
                  onChange={(levelId) => setLevel(row.key, axisKey, levelId)}
                  disabled={disabled || (row.retired && !savedRow)}
                />
              ))}
            </div>
          </div>
        );
      })}
      {mode === "persona" && !personasOffered && <p className="text-muted">No personas to score.</p>}
    </>
  );
}
