/**
 * Module: modules/risk_management/RiskReviewsPanel
 *
 * The review section of a risk's detail page: the next scheduled
 * review (flagged when overdue), a "Record review" dialog, and the history of
 * past reviews, each with the ratings and treatment count it was made against.
 * A review is immutable; a mistake is corrected by recording a newer one. The
 * dialog takes an outcome (Confirmed: the assessment and treatment still stand;
 * Reassessed: the reviewer changed them), required notes, and the next review
 * date — empty means no further review is scheduled.
 *
 * The button always renders: the backend allows the risk's owner or a Risk
 * Manager, and refuses an archived or closed risk, a past next date, and
 * Confirmed while a treatment still needs reassessment; those messages show in
 * the dialog.
 */
import { useEffect, useState } from "react";

import type { ScoringScheme } from "../../api/scoring";
import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { riskApi } from "./api";
import { RiskRatingBadge } from "./RiskRatingBadge";
import { bandTone } from "./useRiskScheme";
import {
  RISK_REVIEW_OUTCOME_LABEL, RISK_REVIEW_OUTCOME_TONE, RISK_STATUS_LABEL,
} from "./types";
import type { Risk, RiskReview, RiskReviewOutcome } from "./types";
import { Badge } from "../../components/Badge";

/**
 * @param risk The risk being reviewed.
 * @param scheme The project's `risk` scheme, to colour the stored rating labels.
 * @param userNames Display names by user id, for the Reviewed by column.
 * @param onRecorded Called after a review was saved, so the page reloads the risk (its review date moves).
 */
export function RiskReviewsPanel({
  risk, scheme, userNames, onRecorded,
}: {
  risk: Risk;
  scheme: ScoringScheme | null;
  userNames: Record<string, string>;
  onRecorded: () => void;
}) {
  const { showToast } = useToast();
  const [reviews, setReviews] = useState<RiskReview[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [outcome, setOutcome] = useState<RiskReviewOutcome>("confirmed");
  const [notes, setNotes] = useState("");
  const [nextDate, setNextDate] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let active = true;
    riskApi
      .listReviews(risk.project_id, risk.id)
      .then((loaded) => {
        if (!active) return;
        setReviews(loaded);
        setLoadError(null);
      })
      .catch((err) => active && setLoadError(toErrorMessage(err, "Could not load this risk's reviews.")));
    return () => {
      active = false;
    };
  }, [risk.project_id, risk.id, reload]);

  function close() {
    setRecording(false);
    setError(null);
  }

  async function save() {
    setError(null);
    try {
      await riskApi.recordReview(risk.project_id, risk.id, { outcome, notes, next_review_date: nextDate || null });
      showToast("Review recorded.");
      setRecording(false);
      setOutcome("confirmed");
      setNotes("");
      setNextDate("");
      setReload((n) => n + 1);
      onRecorded();
    } catch (err) {
      setError(toErrorMessage(err, "Could not record this review."));
    }
  }

  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (reviews === null) return <Spinner />;

  return (
    <section className="stack" aria-label="Reviews" style={{ borderTop: "1px solid var(--color-border)", paddingTop: "0.75rem" }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ margin: 0, fontSize: "0.95rem" }}>Reviews</h3>
        <button className="btn" onClick={() => setRecording(true)}>Record review</button>
      </div>
      <p className="text-muted" style={{ margin: 0 }}>
        {risk.review_date ? <>Next review: {risk.review_date}</> : "No review scheduled."}
        {risk.is_review_overdue && <> <Badge tone="danger">Overdue</Badge></>}
      </p>
      {reviews.length > 0 && (
        <table className="table" aria-label="Review history">
          <thead>
            <tr>
              <th>Reviewed</th><th>By</th><th>Outcome</th><th>Notes</th><th>Status</th><th>Inherent</th><th>Residual</th><th>Next review</th>
            </tr>
          </thead>
          <tbody>
            {[...reviews].reverse().map((r) => (
              <tr key={r.id}>
                <td>{new Date(r.reviewed_at).toLocaleDateString()}</td>
                <td>{userNames[r.reviewed_by] ?? "—"}</td>
                <td>
                  <Badge tone={RISK_REVIEW_OUTCOME_TONE[r.outcome]}>{RISK_REVIEW_OUTCOME_LABEL[r.outcome]}</Badge>
                </td>
                <td style={{ whiteSpace: "pre-wrap" }}>{r.notes}</td>
                <td>{RISK_STATUS_LABEL[r.risk_status]}</td>
                <td><RiskRatingBadge label={r.inherent_rating_label} tone={bandTone(scheme, r.inherent_rating_label)} /></td>
                <td><RiskRatingBadge label={r.residual_rating_label} tone={bandTone(scheme, r.residual_rating_label)} /></td>
                <td>{r.next_review_date ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {recording && (
        <Modal title={`Record review of ${risk.unique_code}`} onClose={close}>
          <div className="stack">
            <LabeledSelect
              label="Outcome"
              value={outcome}
              onChange={(next) => setOutcome(next as RiskReviewOutcome)}
              options={Object.entries(RISK_REVIEW_OUTCOME_LABEL).map(([value, label]) => ({ value, label }))}
              placeholder={null}
            />
            <p className="text-muted" style={{ margin: 0 }}>
              Confirmed: the assessment and treatment still stand. Reassessed: you changed them as part of this review
              (edit the risk first).
            </p>
            <label className="stack" style={{ gap: "0.25rem" }}>
              <span>Review notes</span>
              <textarea className="input" rows={3} aria-label="Review notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
            </label>
            <label className="stack" style={{ gap: "0.25rem" }}>
              <span>Next review date</span>
              <input className="input" type="date" aria-label="Next review date" value={nextDate} onChange={(e) => setNextDate(e.target.value)} />
            </label>
            <p className="text-muted" style={{ margin: 0 }}>Leave the date empty to schedule no further review.</p>
            {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button className="btn" onClick={close}>Cancel</button>
              <button className="btn btn-primary" disabled={!notes.trim()} onClick={save}>Save review</button>
            </div>
          </div>
        </Modal>
      )}
    </section>
  );
}
