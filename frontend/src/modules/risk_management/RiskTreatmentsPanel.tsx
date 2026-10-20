/**
 * Module: modules/risk_management/RiskTreatmentsPanel
 *
 * The treatment section of a risk's detail page: the
 * requirements, designs and actions linked as a treatment (Mitigated by, Treated
 * by), each with the risk owner's verdict on whether it *effectively* reduces the
 * risk — a link alone only proposes one. A risk counts as treated only through
 * Effective verdicts. A verdict that the backend marked "Needs reassessment"
 * (the artefact behind it changed) shows why. Treatment links are made in the
 * Links panel; this panel assesses them.
 *
 * Every Assess button always renders: the backend allows the risk's owner or a
 * Risk Manager and a 403 surfaces as a toast. A rationale is required for
 * Effective and Ineffective (409 otherwise, shown in the dialog).
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { getArtefactPath, getArtefactStatusLabel } from "../artefactPaths";
import { riskApi } from "./api";
import {
  TREATMENT_ASSESSMENT_STATUS_LABEL, TREATMENT_ASSESSMENT_STATUS_TONE,
} from "./types";
import type { RiskTreatment, RiskTreatmentList, TreatmentAssessmentStatus } from "./types";
import { Badge } from "../../components/Badge";
import { FormActions } from "../../components/FormActions";
import { TextAreaField } from "../../components/FormFields";

/** The verdicts a person can record; "Needs reassessment" is only ever set by the system. */
const ASSESSABLE: TreatmentAssessmentStatus[] = ["effective", "ineffective", "proposed"];

/**
 * @param projectId The risk's project.
 * @param riskId The risk whose treatments are listed.
 * @param refreshToken Change to reload (e.g. after a link was added in the Links panel).
 * @param onChanged Called after a verdict was saved, so the page can reload the risk's derived fields.
 */
export function RiskTreatmentsPanel({
  projectId, riskId, refreshToken = 0, onChanged,
}: {
  projectId: string;
  riskId: string;
  refreshToken?: number;
  onChanged?: () => void;
}) {
  const { showToast } = useToast();
  const [list, setList] = useState<RiskTreatmentList | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [assessing, setAssessing] = useState<RiskTreatment | null>(null);
  const [status, setStatus] = useState<TreatmentAssessmentStatus>("effective");
  const [rationale, setRationale] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let active = true;
    riskApi
      .listTreatments(projectId, riskId)
      .then((loaded) => {
        if (!active) return;
        setList(loaded);
        setLoadError(null);
      })
      .catch((err) => active && setLoadError(toErrorMessage(err, "Could not load this risk's treatments.")));
    return () => {
      active = false;
    };
  }, [projectId, riskId, refreshToken, reload]);

  function open(treatment: RiskTreatment) {
    setAssessing(treatment);
    // Assessing a proposed or stale verdict most often means confirming it works.
    setStatus(treatment.status === "ineffective" ? "ineffective" : "effective");
    setRationale(treatment.rationale);
    setError(null);
  }

  async function save() {
    if (!assessing) return;
    setError(null);
    try {
      await riskApi.assessTreatment(projectId, riskId, assessing.link_id, status, rationale);
      showToast("Treatment assessed.");
      setAssessing(null);
      setReload((n) => n + 1);
      onChanged?.();
    } catch (err) {
      setError(toErrorMessage(err, "Could not assess this treatment."));
    }
  }

  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (list === null) return <Spinner />;

  return (
    <section className="stack" aria-label="Treatments" style={{ borderTop: "1px solid var(--color-border)", paddingTop: "0.75rem" }}>
      <h3 style={{ margin: 0, fontSize: "0.95rem" }}>Treatments</h3>
      <p className="text-muted" style={{ margin: 0 }}>
        {list.effective_count === 0
          ? "No effective treatment yet. Link a requirement, design or action in the Links panel, then assess whether it reduces this risk."
          : `${list.effective_count} effective treatment${list.effective_count === 1 ? "" : "s"}.`}
        {list.needs_reassessment_count > 0 && ` ${list.needs_reassessment_count} need${list.needs_reassessment_count === 1 ? "s" : ""} reassessment.`}
      </p>
      {list.items.length > 0 && (
        <table className="table" aria-label="Treatment links">
          <thead>
            <tr><th>Treatment</th><th>Relationship</th><th>Verdict</th><th>Rationale</th><th><span className="sr-only">Actions</span></th></tr>
          </thead>
          <tbody>
            {list.items.map((t) => {
              const path = getArtefactPath(t.other_type, t.other_project_id ?? projectId, t.other_id);
              const otherStatus = getArtefactStatusLabel(t.other_type, t.other_status);
              return (
                <tr key={t.link_id}>
                  <td>
                    <span className="text-muted">{t.other_type_label} </span>
                    {path ? <Link to={path}>{t.label}</Link> : t.label}
                    {otherStatus && <span className="text-muted"> ({otherStatus})</span>}
                  </td>
                  <td>{t.relationship}</td>
                  <td>
                    <Badge tone={TREATMENT_ASSESSMENT_STATUS_TONE[t.status]}>
                      {TREATMENT_ASSESSMENT_STATUS_LABEL[t.status]}
                    </Badge>
                  </td>
                  <td>
                    {t.rationale || "—"}
                    {t.status === "needs_reassessment" && t.reassessment_reason && (
                      <div className="text-muted">{t.reassessment_reason}</div>
                    )}
                  </td>
                  <td>
                    <button className="btn" aria-label={`Assess ${t.label}`} onClick={() => open(t)}>Assess</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {list.hidden_count > 0 && (
        <p className="text-muted" style={{ margin: 0 }}>
          {list.hidden_count} further treatment link{list.hidden_count === 1 ? " points" : "s point"} to records you cannot view.
        </p>
      )}

      {assessing && (
        <Modal title={`Assess ${assessing.label}`} onClose={() => setAssessing(null)}>
          <div className="stack">
            <LabeledSelect helpNotNeeded
              label="Verdict"
              value={status}
              onChange={(next) => setStatus(next as TreatmentAssessmentStatus)}
              options={ASSESSABLE.map((s) => ({ value: s, label: TREATMENT_ASSESSMENT_STATUS_LABEL[s] }))}
              placeholder={null}
            />
            <TextAreaField helpNotNeeded required={status !== "proposed"} label="Rationale" value={rationale} onChange={setRationale} rows={3} />
            <p className="text-muted" style={{ margin: 0 }}>A rationale is needed to mark a treatment Effective or Ineffective.</p>
            <FormActions error={error} onCancel={() => setAssessing(null)} onSave={save} />
          </div>
        </Modal>
      )}
    </section>
  );
}
