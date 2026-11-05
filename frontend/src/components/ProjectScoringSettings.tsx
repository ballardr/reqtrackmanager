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
  projectScoringApi, SCORING_SOURCE_LABEL, scoringOriginLabel, scoringOwnsCriterion, type ScoringLevel, type ScoringScheme,
} from "../api/scoring";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { Badge } from "./Badge";
import { DefinitionList } from "./DefinitionList";
import { LabeledSelect } from "./LabeledSelect";
import { OverridePill } from "./OverridePill";
import { ScoringCriteria } from "./ScoringCriteria";
import { ScoringEnabledModels } from "./ScoringEnabledModels";
import { ScoringModelBands } from "./ScoringModelBands";
import { levelFields, parseLevel } from "./scoringLevelFields";
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
      <section className="stack" aria-labelledby={`${schemeKey}-project-default-model`}>
        <h3 id={`${schemeKey}-project-default-model`} style={{ margin: 0 }}>Default model</h3>
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
      </section>

      {scheme.side_by_side_models && (
        <section className="stack" aria-labelledby={`${schemeKey}-project-enabled-models`}>
          <h3 id={`${schemeKey}-project-enabled-models`} style={{ margin: 0 }}>Models shown</h3>
          <p className="text-muted" style={{ margin: 0 }}>Each record is scored by every model ticked here, side by side.</p>
          <ScoringEnabledModels
            scheme={scheme}
            custom={scheme.enabled_models_source === "project"}
            resetLabel={RESET_LABEL}
            onSave={(models) => mutate(() => criteria.setEnabledModels(models), "Models shown saved.")}
            onReset={() => mutate(() => criteria.setEnabledModels(null), "Models shown reset.")}
          />
        </section>
      )}

      <ScoringCriteria scheme={scheme} calls={criteria} projectId={projectId} onChange={setScheme} />

      <section className="stack" aria-labelledby={`${schemeKey}-project-levels`}>
        <h3 id={`${schemeKey}-project-levels`} style={{ margin: 0 }}>Levels</h3>
        <p className="text-muted" style={{ margin: 0 }}>
          Levels are set by the organisation{scheme.allow_custom_criteria ? ", except for an axis this project defined" : ""}.
        </p>
        {scheme.axes.map((axis) => scoringOwnsCriterion(axis.origin, axis.owner_project_id, projectId) ? (
          <div key={axis.key} className="stack" style={{ gap: "var(--space-2)" }}>
            <h4 style={{ margin: 0 }}>{axis.label} <Badge>{scoringOriginLabel(axis.origin, axis.owner_project_id, projectId)}</Badge></h4>
            <DefinitionList<ScoringLevel>
              items={axis.levels}
              minItems={2}
              fields={levelFields(axis)}
              getReassignLabel={(l) => l.name}
              onRename={async (id, values) => {
                await projectScoringApi.updateLevel(projectId, schemeKey, id, parseLevel(values, !!axis.derived_source));
                showToast("Level saved.");
                reload();
              }}
              onAdd={async (values) => {
                await projectScoringApi.createLevel(projectId, schemeKey, axis.key, parseLevel(values, !!axis.derived_source));
                showToast("Level added.");
                reload();
              }}
              onDelete={async (id, reassignToId) => {
                await projectScoringApi.deleteLevel(projectId, schemeKey, id, reassignToId);
                showToast("Level deleted.");
                reload();
              }}
              deleteLabel={`Delete ${axis.label} level`}
              addLabel={`Add ${axis.label} level`}
            />
          </div>
        ) : (
          <div key={axis.key}>
            <strong>{axis.label}:</strong> {axis.levels.map((l) => `${l.name} (${l.weight})`).join(" · ")}
          </div>
        ))}
      </section>

      <section className="stack" aria-labelledby={`${schemeKey}-project-bands`}>
        <h3 id={`${schemeKey}-project-bands`} style={{ margin: 0 }}>Rating bands</h3>
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
      </section>
    </div>
  );
}
