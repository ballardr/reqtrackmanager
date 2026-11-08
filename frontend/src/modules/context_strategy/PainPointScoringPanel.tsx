/**
 * Module: modules/context_strategy/PainPointScoringPanel
 *
 * The scoring section of a Pain Point's detail page: rate the Pain Point on
 * every criterion the project offers (General), add the personas whose
 * per-persona criteria differ, and see the roll-up under a model and persona
 * roll-up chosen right here ("chosen when viewing").
 *
 * Built from the generic scoring core's shared pieces (`ScoringLevelPicker`,
 * `ScoringModelSwitcher`, the `projectScoringApi` scheme read); the persona
 * list arrives from the backend's `available_targets`, so this module never
 * knows the Stakeholders module exists. If personas are not available, only the
 * General scores are offered. Existing rows whose persona has since
 * vanished stay editable as "Persona unavailable" so they can be removed.
 *
 * Like the rest of this page, the controls always render and the backend's
 * RBAC surfaces as a toast; they are disabled only once the Pain Point is
 * locked (a terminal outcome).
 */
import { useCallback, useEffect, useState } from "react";

import { projectScoringApi, type ScoringScheme } from "../../api/scoring";
import { ScoringModelSwitcher } from "../../components/ScoringModelSwitcher";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectPainPointApi } from "./api";
import { BlockerBadge, PainPointScoreBadge } from "./PainPointScoreBadges";
import { PainPointScoreFields } from "./PainPointScoreFields";
import { GENERAL_KEY, draftFromEntries, scoreInputsFromDraft, type ScoreDraft, type ScoreRow } from "./painPointScoreDraft";
import { PAIN_POINT_ROLLUP_LABEL } from "./types";
import type { PainPointRollup, PainPointScores } from "./types";
import { DetailCard } from "../../components/DetailCard";

const SCHEME_KEY = "pain_point";
/**
 * @param projectId The Pain Point's project.
 * @param painPointId The Pain Point being scored.
 * @param locked True once the Pain Point reached a terminal outcome; disables editing.
 */
export function PainPointScoringPanel({
  projectId, painPointId, locked,
}: {
  projectId: string;
  painPointId: string;
  locked: boolean;
}) {
  const { showToast } = useToast();
  const [scheme, setScheme] = useState<ScoringScheme | null>(null);
  const [scores, setScores] = useState<PainPointScores | null>(null);
  const [model, setModel] = useState<string | null>(null);
  const [rollup, setRollup] = useState<PainPointRollup>("weighted_average");
  const [draft, setDraft] = useState<ScoreDraft>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const adopt = useCallback((loaded: PainPointScores) => {
    setScores(loaded);
    setDraft(draftFromEntries(loaded.entries));
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([projectScoringApi.get(projectId, SCHEME_KEY), projectPainPointApi.getScores(projectId, painPointId)])
      .then(([loadedScheme, loaded]) => {
        if (cancelled) return;
        setScheme(loadedScheme);
        setModel(loaded.model_key);
        adopt(loaded);
      })
      .catch((err) => { if (!cancelled) setLoadError(toErrorMessage(err, "Could not load this Pain Point's scoring.")); });
    return () => { cancelled = true; };
  }, [projectId, painPointId, adopt]);

  // Re-roll-up under a newly chosen model/method without touching unsaved edits.
  async function refreshRollup(nextModel: string, nextRollup: PainPointRollup) {
    try {
      setScores(await projectPainPointApi.getScores(projectId, painPointId, { model_key: nextModel, rollup: nextRollup }));
    } catch (err) {
      showToast(toErrorMessage(err, "Could not recalculate the score."), "error");
    }
  }

  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (scheme === null || scores === null || model === null) return <Spinner />;

  const savedByKey = new Map(scores.entries.map((e) => [e.target_id ?? GENERAL_KEY, e]));
  const personaRows: ScoreRow[] = [
    ...scores.available_targets
      .filter((t) => t.is_active || savedByKey.has(t.id))
      .map((t) => ({
        key: t.id, label: t.label, note: t.weight !== null ? `weight ${t.weight}` : "",
        retired: !t.is_active, unavailable: false,
      })),
    ...scores.entries
      .filter((e) => e.status === "unavailable" && e.target_id)
      .map((e) => ({ key: e.target_id as string, label: "Persona unavailable", note: "", retired: false, unavailable: true })),
  ];

  async function save() {
    const payload = scoreInputsFromDraft(draft);
    setSaving(true);
    try {
      const saved = await projectPainPointApi.setScores(projectId, painPointId, payload, { model_key: model ?? undefined, rollup });
      adopt(saved);
      showToast("Scores saved.");
    } catch (err) {
      showToast(toErrorMessage(err, "Could not save the scores."), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <DetailCard heading="Scoring">
      <ScoringModelSwitcher
        models={scheme.models
          .filter((m) => !scheme.enabled_model_keys?.length || scheme.enabled_model_keys.includes(m.key) || m.key === model)
          .map((m) => ({ value: m.key, label: m.label }))}
        model={model}
        onModelChange={(next) => { setModel(next); void refreshRollup(next, rollup); }}
        rollups={Object.entries(PAIN_POINT_ROLLUP_LABEL).map(([value, label]) => ({ value, label }))}
        rollup={rollup}
        onRollupChange={(next) => { setRollup(next as PainPointRollup); void refreshRollup(model, next as PainPointRollup); }}
      />
      <div className="row" role="group" style={{ gap: "var(--space-3)", alignItems: "center", flexWrap: "wrap" }} aria-label="Rolled-up score">
        <PainPointScoreBadge score={scores.score} />
        <BlockerBadge summary={scores} />
        <span className="text-muted" style={{ fontSize: "0.85rem" }}>
          {scores.scope === "none" ? "Not scored yet." : `${scores.counted} score${scores.counted === 1 ? "" : "s"} counted.`}
        </span>
      </div>
      {scores.personas_degraded && (
        <p className="text-muted" style={{ margin: 0 }}>
          Some scored personas are no longer available, so they are counted without names or weights.
        </p>
      )}

      <PainPointScoreFields
        axes={scheme.axes} personaRows={personaRows} draft={draft} onDraftChange={setDraft}
        disabled={locked} saved={savedByKey}
      />

      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn btn-primary" disabled={locked || saving} onClick={save}>Save scores</button>
      </div>
      {locked && <p className="text-muted" style={{ margin: 0 }}>This Pain Point has reached a terminal outcome; its scores can no longer be edited.</p>}
    </DetailCard>
  );
}
