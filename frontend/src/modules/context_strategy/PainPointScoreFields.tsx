/**
 * Module: modules/context_strategy/PainPointScoreFields
 *
 * The score grid shared by the Pain Point detail page's `PainPointScoringPanel` and the create
 * form: a General group holding every scoring criterion (the whole-Pain-Point ones, and the default
 * for the per-persona ones), then a group for each persona that differs from it, holding the
 * per-persona criteria only. Personas are added one at a time, so the grid stays short however many
 * personas the project has. The page owns the draft (`painPointScoreDraft`) and the buttons; this
 * component only edits it. Saved rows (detail page only) show their score beside the name through
 * `saved`.
 *
 * Personas come from the caller (`personaRows`), so this module never knows the Stakeholders module
 * exists; with none offered, only the General scores can be set.
 */
import { X } from "lucide-react";

import type { ScoringAxis } from "../../api/scoring";
import { Badge } from "../../components/Badge";
import { LabeledSelect } from "../../components/LabeledSelect";
import { ScoringLevelPicker } from "../../components/ScoringLevelPicker";
import { BlockerBadge, PainPointScoreBadge } from "./PainPointScoreBadges";
import { GENERAL_KEY, personaAxes, personaKeys, type ScoreDraft, type ScoreRow } from "./painPointScoreDraft";
import { PAIN_POINT_SCORE_TARGET_STATUS_LABEL } from "./types";
import type { PainPointScoreEntry } from "./types";
import { CONTEXT_STRATEGY_HELP } from "./help";

/**
 * @param axes The scheme's criteria, in display order.
 * @param personaRows Every persona that can hold a row (empty when personas are not available).
 * @param draft The draft being edited.
 * @param onDraftChange Called with the next draft after a level, an added persona or a removed persona.
 * @param disabled Disables every control (a locked Pain Point).
 * @param saved Saved rows by key, to show their score beside the name.
 */
export function PainPointScoreFields({
  axes, personaRows, draft, onDraftChange, disabled = false, saved,
}: {
  axes: ScoringAxis[];
  personaRows: ScoreRow[];
  draft: ScoreDraft;
  onDraftChange: (draft: ScoreDraft) => void;
  disabled?: boolean;
  saved?: Map<string, PainPointScoreEntry>;
}) {
  const perPersona = personaAxes(axes);
  const held = personaKeys(draft);
  const rowFor = (key: string): ScoreRow =>
    personaRows.find((r) => r.key === key) ?? { key, label: "Persona unavailable", note: "", retired: false, unavailable: true };
  const addable = personaRows.filter((r) => !r.retired && !r.unavailable && !(r.key in draft));

  function setLevel(key: string, axisKey: string, levelId: string | null) {
    onDraftChange({ ...draft, [key]: { ...(draft[key] ?? {}), [axisKey]: levelId } });
  }
  function removePersona(key: string) {
    onDraftChange(Object.fromEntries(Object.entries(draft).filter(([held]) => held !== key)));
  }

  const group = (key: string, row: ScoreRow, rowAxes: ScoringAxis[], removable: boolean) => {
    const savedRow = saved?.get(key);
    const values = draft[key] ?? {};
    return (
      <div key={key} className="stack" role="group" aria-label={`${row.label} scores`}>
        <div className="row" style={{ gap: "var(--space-3)", alignItems: "center", flexWrap: "wrap" }}>
          <strong>{row.label}</strong>
          {row.note && <span className="text-muted">{row.note}</span>}
          {row.retired && <Badge tone="muted">{PAIN_POINT_SCORE_TARGET_STATUS_LABEL.inactive}</Badge>}
          {savedRow && <PainPointScoreBadge score={savedRow.score} />}
          {savedRow && <BlockerBadge summary={{ is_blocker: savedRow.is_blocker, blocker_labels: [] }} />}
          {removable && (
            <button type="button" className="btn btn-icon btn-sm" aria-label={`Remove ${row.label} scores`} title="Remove"
              disabled={disabled} onClick={() => removePersona(key)}>
              <X />
            </button>
          )}
        </div>
        <div className="row" style={{ gap: "var(--space-5)", flexWrap: "wrap", alignItems: "flex-start" }}>
          {rowAxes.map((axis) => (
            <ScoringLevelPicker
              key={axis.key} axis={axis} value={values[axis.key] ?? null}
              onChange={(levelId) => setLevel(key, axis.key, levelId)}
              disabled={disabled || (row.retired && !savedRow)}
            />
          ))}
        </div>
      </div>
    );
  };

  return (
    <>
      {group(GENERAL_KEY, { key: GENERAL_KEY, label: "General", note: "", retired: false, unavailable: false }, axes, false)}
      {held.map((key) => group(key, rowFor(key), perPersona, true))}
      {personaRows.length > 0 ? (
        <LabeledSelect
          label="Add a persona that differs" help={CONTEXT_STRATEGY_HELP.scoringPersonaOverride} value=""
          onChange={(key) => key && onDraftChange({ ...draft, [key]: {} })}
          options={addable.map((r) => ({ value: r.key, label: r.label }))}
          placeholder="Select a persona…" disabled={disabled || addable.length === 0}
        />
      ) : (
        <p className="text-muted" style={{ margin: 0 }}>Personas are not available in this project, so only the General scores apply.</p>
      )}
    </>
  );
}
