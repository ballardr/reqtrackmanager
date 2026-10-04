/**
 * Module: components/ProjectScoringSettings
 *
 * Project-level scoring settings for one scheme (generic scoring-matrix
 * core, Module 1 Phase 10): override the default model and rating bands,
 * or inherit them (nearest ancestor project → organisation → module
 * default — Phase 9 Q3, Decided by: User). Levels are organisation-wide and
 * shown read-only here. A module embeds this in its own project-admin
 * section with its scheme key; every inherited value says where it comes
 * from (`OverridePill`), and every mutation toasts its outcome.
 */
import { useEffect, useState } from "react";

import { projectScoringApi, SCORING_SOURCE_LABEL, type ScoringScheme } from "../api/scoring";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { LabeledSelect } from "./LabeledSelect";
import { OverridePill } from "./OverridePill";
import { ScoringModelBands } from "./ScoringModelBands";
import { Spinner } from "./Spinner";

const RESET_LABEL = "Use inherited value";

/**
 * @param projectId The project being configured.
 * @param schemeKey The registered scoring scheme key.
 */
export function ProjectScoringSettings({ projectId, schemeKey }: { projectId: string; schemeKey: string }) {
  const { showToast } = useToast();
  const [scheme, setScheme] = useState<ScoringScheme | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

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
  }, [projectId, schemeKey]);

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

  return (
    <div className="stack">
      <section className="stack" aria-labelledby={`${schemeKey}-project-default-model`}>
        <h3 id={`${schemeKey}-project-default-model`} style={{ margin: 0 }}>Default model</h3>
        <div className="row" style={{ gap: "0.75rem", alignItems: "flex-end", flexWrap: "wrap" }}>
          <LabeledSelect
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

      <section className="stack" aria-labelledby={`${schemeKey}-project-levels`}>
        <h3 id={`${schemeKey}-project-levels`} style={{ margin: 0 }}>Levels</h3>
        <p className="text-muted" style={{ margin: 0 }}>Levels are set by the organisation.</p>
        {scheme.axes.map((axis) => (
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
        />
      </section>
    </div>
  );
}
