/**
 * Module: components/ScoringSchemeEditor
 *
 * Org-level configuration of one scoring scheme (generic scoring-matrix
 * core, Module 1 Phase 10): each axis's levels, the org default model, and
 * each model's rating bands. A module embeds this in its own org-admin
 * section, passing its scheme key (e.g. Context & Strategy's "pain_point")
 * — core never knows which modules score what (Decided by: User, Phase 10
 * sign-off: scoring config sits beside the feature it scores).
 *
 * Levels reuse the shared `DefinitionList` (inline edit, delete with
 * reassign-on-409), ordered by weight rather than manually. Every mutation
 * reports success or failure through the shared toast. Permission is
 * enforced server-side; a 403 surfaces as an error toast.
 */
import { useEffect, useState } from "react";

import { orgScoringApi, SCORING_SOURCE_LABEL, type ScoringLevel, type ScoringScheme } from "../api/scoring";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { DefinitionList } from "./DefinitionList";
import { LabeledSelect } from "./LabeledSelect";
import { OverridePill } from "./OverridePill";
import { ScoringModelBands } from "./ScoringModelBands";
import { Spinner } from "./Spinner";

function parseLevel(values: Record<string, string>) {
  const weight = Number(values.weight);
  if (!Number.isFinite(weight) || weight <= 0) throw new Error("Weight must be a positive number.");
  return { name: values.name.trim(), weight, description: values.description.trim() || null };
}

/**
 * @param orgId The organisation being configured.
 * @param schemeKey The registered scoring scheme key.
 */
export function ScoringSchemeEditor({ orgId, schemeKey }: { orgId: string; schemeKey: string }) {
  const { showToast } = useToast();
  const [scheme, setScheme] = useState<ScoringScheme | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const reload = () => setReloadKey((k) => k + 1);

  useEffect(() => {
    let cancelled = false;
    orgScoringApi.get(orgId, schemeKey)
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
  }, [orgId, schemeKey, reloadKey]);

  /** Runs a mutation and toasts the outcome; `after` applies its result,
   * otherwise the scheme is re-fetched. */
  async function mutate(action: () => Promise<unknown>, success: string, after?: (result: unknown) => void) {
    try {
      const result = await action();
      if (after) after(result);
      else reload();
      showToast(success);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not save scoring settings."), "error");
    }
  }

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (!scheme) return <Spinner />;
  const applySchemeResult = (result: unknown) => setScheme(result as ScoringScheme);

  return (
    <div className="stack">
      <section className="stack" aria-labelledby={`${schemeKey}-default-model`}>
        <h3 id={`${schemeKey}-default-model`} style={{ margin: 0 }}>Default model</h3>
        <p className="text-muted" style={{ margin: 0 }}>
          Used unless a project sets its own; anyone viewing scores can still switch model.
        </p>
        <div className="row" style={{ gap: "0.75rem", alignItems: "flex-end", flexWrap: "wrap" }}>
          <LabeledSelect
            label="Default model"
            value={scheme.default_model_key}
            placeholder={null}
            options={scheme.models.map((m) => ({ value: m.key, label: m.label }))}
            onChange={(model) =>
              void mutate(() => orgScoringApi.setDefaultModel(orgId, schemeKey, model), "Default model saved.", applySchemeResult)}
          />
          <OverridePill
            custom={scheme.default_model_source === "org"}
            defaultLabel={SCORING_SOURCE_LABEL.system}
            resetLabel="Reset to module default"
            onReset={() =>
              void mutate(() => orgScoringApi.setDefaultModel(orgId, schemeKey, null), "Default model reset.", applySchemeResult)}
          />
        </div>
      </section>

      <section className="stack" aria-labelledby={`${schemeKey}-levels`}>
        <h3 id={`${schemeKey}-levels`} style={{ margin: 0 }}>Levels</h3>
        <p className="text-muted" style={{ margin: 0 }}>
          Levels are ordered by weight; a model's score multiplies the chosen levels' weights. Every axis keeps at least
          two levels, and the highest weight is the axis's top level.
        </p>
        {scheme.axes.map((axis) => (
          <div key={axis.key} className="stack" style={{ gap: "0.35rem" }}>
            <h4 style={{ margin: 0 }}>{axis.label}</h4>
            {axis.description && <span className="text-muted">{axis.description}</span>}
            <DefinitionList<ScoringLevel>
              items={axis.levels}
              minItems={2}
              fields={[
                { key: "name", getValue: (l) => l.name, placeholder: "Level name", ariaLabel: `${axis.label} level name`, maxWidth: 180 },
                { key: "weight", getValue: (l) => String(l.weight), placeholder: "Weight", ariaLabel: `${axis.label} level weight`, maxWidth: 90, inputType: "number" },
                { key: "description", getValue: (l) => l.description ?? "", placeholder: "Guidance (optional)", ariaLabel: `${axis.label} level guidance`, maxWidth: 360, optional: true },
              ]}
              getReassignLabel={(l) => l.name}
              onRename={async (id, values) => {
                await orgScoringApi.updateLevel(orgId, schemeKey, id, parseLevel(values));
                showToast("Level saved.");
                reload();
              }}
              onAdd={async (values) => {
                await orgScoringApi.createLevel(orgId, schemeKey, axis.key, parseLevel(values));
                showToast("Level added.");
                reload();
              }}
              onDelete={async (id, reassignToId) => {
                await orgScoringApi.deleteLevel(orgId, schemeKey, id, reassignToId);
                showToast("Level deleted.");
                reload();
              }}
              deleteLabel={`Delete ${axis.label} level`}
              addLabel={`Add ${axis.label} level`}
            />
          </div>
        ))}
      </section>

      <section className="stack" aria-labelledby={`${schemeKey}-bands`}>
        <h3 id={`${schemeKey}-bands`} style={{ margin: 0 }}>Rating bands</h3>
        <ScoringModelBands
          scheme={scheme}
          isCustom={(m) => m.bands_source === "org"}
          resetLabel="Reset to module default"
          onSave={(model, bands) =>
            mutate(() => orgScoringApi.setBands(orgId, schemeKey, model, bands), "Rating bands saved.", applySchemeResult)}
          onReset={(model) =>
            mutate(() => orgScoringApi.setBands(orgId, schemeKey, model, null), "Rating bands reset.", applySchemeResult)}
        />
      </section>
    </div>
  );
}
