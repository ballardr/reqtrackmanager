/**
 * Module: components/ScoringCriteria
 *
 * The "Criteria" block shared by the organisation `ScoringSchemeEditor` and the project `ProjectScoringSettings`
 * (generic scoring-matrix core), shown only for a scheme that takes custom criteria. It lists the axes and models the
 * tier can see with who defined each: ones the tier defined itself can be edited and deleted, every other one can only
 * be hidden here (and restored from the "Hidden" list), so a registered or inherited criterion is never destroyed.
 * Adding and editing go through `ScoringAxisFormModal` and `ScoringModelFormModal`.
 *
 * The caller passes the tier's calls (`ScoringCriteriaCalls`) and receives each refreshed scheme through `onChange`;
 * every mutation reports its outcome through the shared toast, and a failure inside a dialog stays in the dialog.
 * Deleting an axis that scores use asks first and then drops those scores (`clear_scores`).
 */
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import {
  scoringOriginLabel, scoringOwnsCriterion, type ScoringAxis, type ScoringCriteriaCalls, type ScoringModel, type ScoringScheme,
} from "../api/scoring";
import { ApiError } from "../api/client";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";
import { ScoringAxisFormModal } from "./ScoringAxisFormModal";
import { ScoringModelFormModal } from "./ScoringModelFormModal";

type Dialog =
  | { kind: "axis"; axis?: ScoringAxis }
  | { kind: "model"; model?: ScoringModel }
  | { kind: "delete-axis"; axis: ScoringAxis; scores?: string }
  | { kind: "delete-model"; model: ScoringModel }
  | { kind: "hide"; criterion: "axis" | "model"; key: string; label: string };

/**
 * @param scheme The tier's effective scheme.
 * @param calls The tier's criteria calls (organisation or project).
 * @param projectId The project being edited; omit for the organisation, whose own criteria are the "Organisation" ones.
 * @param onChange Receives the refreshed scheme after each successful change.
 */
export function ScoringCriteria({
  scheme, calls, projectId, onChange,
}: {
  scheme: ScoringScheme;
  calls: ScoringCriteriaCalls;
  projectId?: string;
  onChange: (scheme: ScoringScheme) => void;
}) {
  const { showToast } = useToast();
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!scheme.allow_custom_criteria) return null;

  const close = () => { setDialog(null); setError(null); };

  /** Runs a call from a dialog: success closes it and toasts, failure stays in the dialog. */
  async function submit(action: () => Promise<ScoringScheme>, success: string) {
    try {
      onChange(await action());
      showToast(success);
      close();
    } catch (err) {
      setError(toErrorMessage(err, "Could not save the scoring criteria."));
    }
  }

  /** Runs a call from a button: success toasts, failure toasts as an error. */
  async function run(action: () => Promise<ScoringScheme>, success: string) {
    try {
      onChange(await action());
      showToast(success);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not save the scoring criteria."), "error");
    }
  }

  /** Deletes an axis; a 409 about stored scores becomes a confirmation to drop them, any other 409 is shown as is. */
  async function deleteAxis(axis: ScoringAxis, clearScores: boolean) {
    try {
      onChange(await calls.deleteAxis(axis.key, clearScores));
      showToast("Axis deleted.");
      close();
    } catch (err) {
      if (!clearScores && err instanceof ApiError && err.status === 409 && /score\(s\)/.test(err.message)) {
        setDialog({ kind: "delete-axis", axis, scores: err.message });
        return;
      }
      close();
      showToast(toErrorMessage(err, "Could not delete the axis."), "error");
    }
  }

  const badges = (origin: ScoringAxis["origin"], owner: string | null | undefined) => (
    <Badge>{scoringOriginLabel(origin, owner, projectId)}</Badge>
  );

  return (
    <section className="stack" aria-labelledby={`${scheme.key}-criteria`}>
      <h3 id={`${scheme.key}-criteria`} style={{ margin: 0 }}>Criteria</h3>
      <p className="text-muted" style={{ margin: 0 }}>
        Define your own axes and models beside the built-in ones. Ones you define can be edited or deleted; any other can
        only be hidden{projectId ? " in this project" : ""}, and restored later. Scores already stored are kept.
      </p>

      <h4 style={{ margin: 0 }}>Axes</h4>
      <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0, gap: "var(--space-2)" }}>
        {scheme.axes.map((axis) => {
          const own = scoringOwnsCriterion(axis.origin, axis.owner_project_id, projectId);
          return (
            <li key={axis.key} className="row" style={{ gap: "var(--space-3)" }}>
              <strong>{axis.label}</strong>
              {badges(axis.origin, axis.owner_project_id)}
              {axis.derived_source && <Badge tone="info">Worked out from demand</Badge>}
              {own ? (
                <>
                  <button type="button" className="btn btn-icon btn-sm" aria-label={`Edit ${axis.label}`} title="Edit" onClick={() => setDialog({ kind: "axis", axis })}><Pencil /></button>
                  <button type="button" className="btn btn-icon btn-sm" aria-label={`Delete ${axis.label}`} title="Delete" onClick={() => setDialog({ kind: "delete-axis", axis })}><Trash2 /></button>
                </>
              ) : (
                <button type="button" className="btn btn-sm" aria-label={`Hide ${axis.label}`} onClick={() => setDialog({ kind: "hide", criterion: "axis", key: axis.key, label: axis.label })}>Hide</button>
              )}
            </li>
          );
        })}
      </ul>
      <div><button type="button" className="btn" onClick={() => setDialog({ kind: "axis" })}><Plus /> Add axis</button></div>

      <h4 style={{ margin: 0 }}>Models</h4>
      <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0, gap: "var(--space-2)" }}>
        {scheme.models.map((model) => {
          const own = scoringOwnsCriterion(model.origin, model.owner_project_id, projectId);
          return (
            <li key={model.key} className="row" style={{ gap: "var(--space-3)" }}>
              <strong>{model.label}</strong>
              {badges(model.origin, model.owner_project_id)}
              <Badge>{model.combination === "weighted_sum" ? "Weighted sum" : "Product"}</Badge>
              {own ? (
                <>
                  <button type="button" className="btn btn-icon btn-sm" aria-label={`Edit ${model.label}`} title="Edit" onClick={() => setDialog({ kind: "model", model })}><Pencil /></button>
                  <button type="button" className="btn btn-icon btn-sm" aria-label={`Delete ${model.label}`} title="Delete" onClick={() => setDialog({ kind: "delete-model", model })}><Trash2 /></button>
                </>
              ) : (
                <button type="button" className="btn btn-sm" aria-label={`Hide ${model.label}`} onClick={() => setDialog({ kind: "hide", criterion: "model", key: model.key, label: model.label })}>Hide</button>
              )}
            </li>
          );
        })}
      </ul>
      <div><button type="button" className="btn" onClick={() => setDialog({ kind: "model" })}><Plus /> Add model</button></div>

      {(scheme.hidden_criteria ?? []).length > 0 && (
        <>
          <h4 style={{ margin: 0 }}>Hidden</h4>
          <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0, gap: "var(--space-2)" }}>
            {(scheme.hidden_criteria ?? []).map((h) => (
              <li key={`${h.kind}:${h.key}`} className="row" style={{ gap: "var(--space-3)" }}>
                <span>{h.label}</span>
                <Badge>{h.kind === "axis" ? "Axis" : "Model"}</Badge>
                <button type="button" className="btn btn-sm" aria-label={`Restore ${h.label}`}
                  onClick={() => void run(() => calls.restoreCriterion({ kind: h.kind, key: h.key }), `${h.label} restored.`)}>
                  Restore
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      {dialog?.kind === "axis" && (
        <ScoringAxisFormModal
          initial={dialog.axis} error={error} onCancel={close}
          onSave={(values) => void submit(
            () => dialog.axis ? calls.updateAxis(dialog.axis.key, { label: values.label, description: values.description }) : calls.createAxis(values),
            dialog.axis ? "Axis saved." : "Axis added.",
          )}
        />
      )}
      {dialog?.kind === "model" && (
        <ScoringModelFormModal
          initial={dialog.model} axes={scheme.axes} error={error} onCancel={close}
          onSave={(input) => void submit(
            () => dialog.model ? calls.updateModel(dialog.model.key, input) : calls.createModel(input),
            dialog.model ? "Model saved." : "Model added.",
          )}
        />
      )}
      {dialog?.kind === "delete-axis" && (
        <ConfirmDialog
          title={dialog.scores ? "Delete axis and its scores?" : `Delete ${dialog.axis.label}?`}
          confirmLabel={dialog.scores ? "Delete axis and scores" : "Delete axis"} onCancel={close}
          message={dialog.scores
            ? `${dialog.scores.replace(/; delete it with clear_scores to drop them\.?$/, ".")} Deleting the axis removes those scores. This cannot be undone.`
            : "The axis and its levels are removed. A model that uses it must be changed or deleted first."}
          onConfirm={() => void deleteAxis(dialog.axis, !!dialog.scores)}
        />
      )}
      {dialog?.kind === "delete-model" && (
        <ConfirmDialog
          title={`Delete ${dialog.model.label}?`} confirmLabel="Delete model" onCancel={close}
          message="The model is removed with its rating bands and wherever it is the default or enabled. Scores stored against the axes are kept."
          onConfirm={() => { const key = dialog.model.key; close(); void run(() => calls.deleteModel(key), "Model deleted."); }}
        />
      )}
      {dialog?.kind === "hide" && (
        <ConfirmDialog
          title={`Hide ${dialog.label}?`} confirmLabel="Hide" onCancel={close}
          message={`${dialog.label} will no longer be offered${projectId ? " in this project" : ""}. Scores already stored are kept, and you can restore it from the Hidden list.`}
          onConfirm={() => { const { criterion, key, label } = dialog; close(); void run(() => calls.hideCriterion({ kind: criterion, key }), `${label} hidden.`); }}
        />
      )}
    </section>
  );
}
