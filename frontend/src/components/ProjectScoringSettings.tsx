/**
 * Module: components/ProjectScoringSettings
 *
 * Project-level scoring settings for one scheme (generic scoring-matrix
 * core): override the default model, the models shown side by side, rating
 * bands and per-cell ratings, or inherit them (nearest ancestor project →
 * organisation → module default, Decided by: User). The project can also
 * define its own axes and models and hide inherited ones (`ScoringCriteria`);
 * levels of an axis it defined are edited here, every other axis's levels are
 * set by the organisation and shown read-only. A module embeds this in its own project-admin
 * section with its scheme key; every inherited value says where it comes
 * from (`OverridePill`), and every mutation toasts its outcome.
 */
import { useEffect, useState } from "react";

import {
  projectScoringApi, SCORING_SOURCE_LABEL, type ScoringScheme,
} from "../api/scoring";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { LabeledSelect } from "./LabeledSelect";
import { OverridePill } from "./OverridePill";
import { ScoringCriteria } from "./ScoringCriteria";
import { ScoringEnabledModels } from "./ScoringEnabledModels";
import { ScoringModelBands } from "./ScoringModelBands";
import { ScoringSection } from "./ScoringSection";
import { ScoringAxisLevels } from "./ScoringAxisLevels";
import { Spinner } from "./Spinner";
import { useStrings } from "../context/TerminologyContext";

const RESET_LABEL = "Use inherited value";

/**
 * @param projectId The project being configured.
 * @param schemeKey The registered scoring scheme key.
 */
export function ProjectScoringSettings({ projectId, schemeKey }: { projectId: string; schemeKey: string }) {
  const strings = useStrings();
  const { showToast } = useToast();
  const [scheme, setScheme] = useState<ScoringScheme | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const reload = () => setReloadKey((k) => k + 1);

  useEffect(() => {
    let cancelled = false;
    projectScoringApi.get(projectId, schemeKey)
      .then((result) => {
        if (cancelled) return;
        setScheme(result);
        setLoadError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError(toErrorMessage(err, "Could not load scoring settings."));
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, schemeKey, reloadKey]);

  async function mutate(action: () => Promise<ScoringScheme>, success: string) {
    try {
      setScheme(await action());
      showToast(success);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not save scoring settings."), "error");
    }
  }

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (!scheme) return <Spinner />;
  const criteria = projectScoringApi.criteria(projectId, schemeKey);

  return (
    <div className="stack">
      <ScoringSection sectionKey={`${schemeKey}:p:default-model`} title="Default model">
        <div className="row" style={{ gap: "var(--space-4)", alignItems: "flex-end", flexWrap: "wrap" }}>
          <LabeledSelect help={strings.help.scoringDefaultModel}
            label="Default model"
            value={scheme.default_model_key}
            placeholder={null}
            options={scheme.models.map((m) => ({ value: m.key, label: m.label }))}
            onChange={(model) =>
              void mutate(() => projectScoringApi.setDefaultModel(projectId, schemeKey, model), "Default model saved.")}
          />
          <OverridePill
            custom={scheme.default_model_source === "project"}
            defaultLabel={SCORING_SOURCE_LABEL[scheme.default_model_source]}
            resetLabel={RESET_LABEL}
            onReset={() =>
              void mutate(() => projectScoringApi.setDefaultModel(projectId, schemeKey, null), "Default model reset.")}
          />
        </div>
      </ScoringSection>

      {scheme.side_by_side_models && (
        <ScoringSection sectionKey={`${schemeKey}:p:enabled-models`} title="Models shown">
          <p className="text-muted" style={{ margin: 0 }}>Each record is scored by every model ticked here, side by side.</p>
          <ScoringEnabledModels
            scheme={scheme}
            custom={scheme.enabled_models_source === "project"}
            resetLabel={RESET_LABEL}
            onSave={(models) => mutate(() => criteria.setEnabledModels(models), "Models shown saved.")}
            onReset={() => mutate(() => criteria.setEnabledModels(null), "Models shown reset.")}
          />
        </ScoringSection>
      )}

      <ScoringCriteria scheme={scheme} calls={criteria} projectId={projectId} onChange={setScheme} />

      <ScoringSection sectionKey={`${schemeKey}:p:levels`} title="Levels">
        <p className="text-muted" style={{ margin: 0 }}>
          Levels are set by the organisation{scheme.allow_custom_criteria ? ", except for an axis this project defined" : ""}.
        </p>
        <ScoringAxisLevels
          scheme={scheme} projectId={projectId} onChanged={reload}
          calls={{
            create: (axisKey, body) => projectScoringApi.createLevel(projectId, schemeKey, axisKey, body),
            update: (id, body) => projectScoringApi.updateLevel(projectId, schemeKey, id, body),
            remove: (id, reassignToId) => projectScoringApi.deleteLevel(projectId, schemeKey, id, reassignToId),
          }}
          thresholdCalls={{ save: (axisKey, thresholds) => projectScoringApi.setAxisThresholds(projectId, schemeKey, axisKey, thresholds) }}
        />
      </ScoringSection>

      <ScoringSection sectionKey={`${schemeKey}:p:bands`} title="Rating bands">
        <ScoringModelBands
          scheme={scheme}
          isCustom={(m) => m.bands_source === "project"}
          resetLabel={RESET_LABEL}
          onSave={(model, bands) => mutate(() => projectScoringApi.setBands(projectId, schemeKey, model, bands), "Rating bands saved.")}
          onReset={(model) => mutate(() => projectScoringApi.setBands(projectId, schemeKey, model, null), "Rating bands reset.")}
          isCellsCustom={(m) => m.cell_ratings_source === "project"}
          onSaveCells={(model, cells) => mutate(() => projectScoringApi.setCellRatings(projectId, schemeKey, model, cells), "Cell ratings saved.")}
          onResetCells={(model) => mutate(() => projectScoringApi.setCellRatings(projectId, schemeKey, model, null), "Cell ratings reset.")}
        />
      </ScoringSection>
    </div>
  );
}
