/**
 * Module: components/ScoringEnabledModels
 *
 * The "Models shown" control shared by the organisation `ScoringSchemeEditor` and the project
 * `ProjectScoringSettings` (generic scoring-matrix core): which of a scheme's models are scored side by side on
 * each record. The set is all-or-nothing per tier and inherited when unset (`OverridePill`), and the default model is
 * always part of it, so its box is ticked and locked. Each tick saves at once; the caller owns the call, the toast
 * and the refreshed scheme.
 */
import { SCORING_SOURCE_LABEL, type ScoringScheme } from "../api/scoring";
import { useStrings } from "../context/TerminologyContext";
import { FieldHelp } from "./FieldHelp";
import { CheckboxField } from "./FormFields";
import { OverridePill } from "./OverridePill";

/**
 * @param scheme The effective scheme (its `enabled_model_keys` is the current set, default model first).
 * @param custom Whether this tier set the list itself rather than inheriting it.
 * @param resetLabel Text of the reset action.
 * @param onSave Saves the whole chosen set (caller owns feedback; must not throw).
 * @param onReset Clears this tier's set so it inherits (same contract).
 */
export function ScoringEnabledModels({
  scheme, custom, resetLabel, platformFallback, onSave, onReset,
}: {
  scheme: ScoringScheme;
  custom: boolean;
  resetLabel: string;
  /** The fallback is the module default on an organisation page: no pill, only a reset while custom. */
  platformFallback?: boolean;
  onSave: (models: string[]) => Promise<void>;
  onReset: () => Promise<void>;
}) {
  const strings = useStrings();
  const enabled = new Set(scheme.enabled_model_keys ?? scheme.models.map((m) => m.key));
  function toggle(key: string, on: boolean) {
    const next = new Set(enabled);
    if (on) next.add(key);
    else next.delete(key);
    void onSave(scheme.models.map((m) => m.key).filter((k) => next.has(k)));
  }
  return (
    <div className="stack" style={{ gap: "var(--space-2)" }}>
      <div className="row" style={{ gap: "var(--space-4)", flexWrap: "wrap" }}>
        <OverridePill
          custom={custom}
          defaultLabel={SCORING_SOURCE_LABEL[scheme.enabled_models_source ?? "system"]}
          resetLabel={resetLabel}
          platformFallback={platformFallback}
          onReset={() => void onReset()}
        />
        <FieldHelp label="Models shown" help={strings.help.scoringEnabledModels} />
      </div>
      {scheme.models.map((m) => {
        const isDefault = m.key === scheme.default_model_key;
        return (
          <CheckboxField
            key={m.key} label={m.label} ariaLabel={`Show ${m.label}`} checked={enabled.has(m.key) || isDefault}
            disabled={isDefault} title={isDefault ? "The default model is always shown." : undefined}
            helpNotNeeded
            onChange={(on) => toggle(m.key, on)}
          />
        );
      })}
    </div>
  );
}
