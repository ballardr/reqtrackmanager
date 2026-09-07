/**
 * Module: modules/compliance/ReviewsPanel
 *
 * Scheduled compliance reviews for one project's standard assignment
 * (§17, §18, §28) — full CRUD + complete, mirroring
 * `project_router.py`'s own project-level review endpoints exactly (a
 * review can only be edited/deleted while still `SCHEDULED`; completing a
 * recurring review schedules the next cycle automatically, so "review
 * history" is simply every row ever created for this assignment, oldest
 * first — see that router's own docstrings).
 *
 * A project's own *unified* due/overdue listing (spanning both this
 * assignment's project-level reviews and any review of the standard
 * itself) is `OutstandingPanel`'s concern, not this one — this panel is
 * the per-assignment CRUD surface, matching `ApplicabilityTree`'s own
 * "one assignment at a time" scope.
 */
import { useEffect, useState } from "react";

import { COMPLIANCE_REVIEW_OUTCOME_LABEL, COMPLIANCE_REVIEW_SCHEDULE_STATE_LABEL, COMPLIANCE_REVIEW_STATUS_LABEL, type ComplianceReviewOutcome, type OrgUser } from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Modal } from "../../components/Modal";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import type { ComplianceReview } from "./types";
import { userDisplayName } from "./types";

export function ReviewsPanel({
  projectId, projectComplianceId, orgUsers,
}: { projectId: string; projectComplianceId: string; orgUsers: OrgUser[] }) {
  const { showToast } = useToast();
  const [reviews, setReviews] = useState<ComplianceReview[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<ComplianceReview | null>(null);
  const [completing, setCompleting] = useState<ComplianceReview | null>(null);
  const [deleting, setDeleting] = useState<ComplianceReview | null>(null);

  async function reload() {
    try {
      setReviews(await complianceApi.listProjectReviews(projectId, projectComplianceId));
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load reviews."), "error");
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, projectComplianceId]);

  if (reviews === null) return <Spinner />;

  return (
    <div className="stack">
      <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>
        Schedule review
      </button>
      {reviews.length === 0 ? (
        <p className="text-muted">No reviews scheduled for this assignment yet.</p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {reviews.map((r) => (
            <li key={r.id} className="card stack" style={{ marginBottom: "0.5rem", padding: "0.6rem 0.85rem" }}>
              <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
                <span>
                  <strong>{r.frequency_label}</strong> — due {r.next_due_date}
                  {r.schedule_state && <span className="badge" style={{ marginLeft: "0.5rem" }}>{COMPLIANCE_REVIEW_SCHEDULE_STATE_LABEL[r.schedule_state]}</span>}
                  <span className="badge" style={{ marginLeft: "0.5rem" }}>{COMPLIANCE_REVIEW_STATUS_LABEL[r.status]}</span>
                </span>
                {r.status === "scheduled" ? (
                  <div className="row">
                    <button className="btn" onClick={() => setEditing(r)}>Edit</button>
                    <button className="btn btn-primary" onClick={() => setCompleting(r)}>Complete</button>
                    <button className="btn btn-danger" onClick={() => setDeleting(r)}>Delete</button>
                  </div>
                ) : (
                  r.outcome && <span className="text-muted">{COMPLIANCE_REVIEW_OUTCOME_LABEL[r.outcome]}</span>
                )}
              </div>
              <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
                Owner: {userDisplayName(orgUsers, r.owner_id)}
                {r.notes && ` — ${r.notes}`}
              </p>
            </li>
          ))}
        </ul>
      )}

      {(creating || editing) && (
        <ReviewFormModal
          initial={editing ?? undefined}
          orgUsers={orgUsers}
          onCancel={() => { setCreating(false); setEditing(null); }}
          onSave={async (values) => {
            try {
              if (editing) {
                await complianceApi.updateProjectReview(projectId, editing.id, values);
                showToast("Review updated.");
              } else {
                await complianceApi.createProjectReview(projectId, projectComplianceId, values);
                showToast("Review scheduled.");
              }
              setCreating(false);
              setEditing(null);
              await reload();
            } catch (err) {
              showToast(toErrorMessage(err, "Could not save review."), "error");
            }
          }}
        />
      )}

      {completing && (
        <CompleteReviewModal
          onCancel={() => setCompleting(null)}
          onSave={async (values) => {
            try {
              await complianceApi.completeProjectReview(projectId, completing.id, values);
              showToast("Review completed.");
              setCompleting(null);
              await reload();
            } catch (err) {
              showToast(toErrorMessage(err, "Could not complete review."), "error");
            }
          }}
        />
      )}

      {deleting && (
        <ConfirmDialog
          title={`Delete "${deleting.frequency_label}"?`}
          message="This review was scheduled by mistake. This cannot be undone."
          confirmLabel="Delete"
          onConfirm={async () => {
            try {
              await complianceApi.deleteProjectReview(projectId, deleting.id);
              showToast("Review deleted.");
              setDeleting(null);
              await reload();
            } catch (err) {
              showToast(toErrorMessage(err, "Could not delete review."), "error");
            }
          }}
          onCancel={() => setDeleting(null)}
        />
      )}
    </div>
  );
}

function ReviewFormModal({
  initial,
  orgUsers,
  onCancel,
  onSave,
}: {
  initial?: ComplianceReview;
  orgUsers: OrgUser[];
  onCancel: () => void;
  onSave: (values: { frequency_label: string; recurrence_days: number | null; next_due_date: string; owner_id: string | null; notes: string }) => void;
}) {
  const [frequencyLabel, setFrequencyLabel] = useState(initial?.frequency_label ?? "");
  const [recurrenceDays, setRecurrenceDays] = useState(initial?.recurrence_days ? String(initial.recurrence_days) : "");
  const [nextDueDate, setNextDueDate] = useState(initial?.next_due_date ?? "");
  const [ownerId, setOwnerId] = useState(initial?.owner_id ?? "");
  const [notes, setNotes] = useState(initial?.notes ?? "");

  return (
    <Modal title={initial ? "Edit review" : "Schedule review"} onClose={onCancel}>
      <div className="stack">
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Frequency / description</span>
          <input className="input" value={frequencyLabel} onChange={(e) => setFrequencyLabel(e.target.value)} placeholder="e.g. Annual security review" aria-label="Frequency label" />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Next due date</span>
          <input className="input" type="date" value={nextDueDate} onChange={(e) => setNextDueDate(e.target.value)} />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Recurs every (days, optional)</span>
          <input className="input" type="number" min={1} value={recurrenceDays} onChange={(e) => setRecurrenceDays(e.target.value)} />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Owner</span>
          <select className="input" value={ownerId} onChange={(e) => setOwnerId(e.target.value)} aria-label="Review owner">
            <option value="">Unassigned</option>
            {orgUsers.map((u) => (
              <option key={u.user_id} value={u.user_id}>{u.display_name}</option>
            ))}
          </select>
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Notes</span>
          <textarea className="input" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button
            className="btn btn-primary"
            disabled={!frequencyLabel.trim() || !nextDueDate}
            onClick={() =>
              onSave({
                frequency_label: frequencyLabel, recurrence_days: recurrenceDays ? Number(recurrenceDays) : null,
                next_due_date: nextDueDate, owner_id: ownerId || null, notes,
              })
            }
          >
            Save
          </button>
        </div>
      </div>
    </Modal>
  );
}

const OUTCOME_OPTIONS: ComplianceReviewOutcome[] = ["satisfactory", "action_required", "unsatisfactory"];

function CompleteReviewModal({
  onCancel,
  onSave,
}: {
  onCancel: () => void;
  onSave: (values: { outcome: ComplianceReviewOutcome; notes: string }) => void;
}) {
  const [outcome, setOutcome] = useState<ComplianceReviewOutcome>("satisfactory");
  const [notes, setNotes] = useState("");

  return (
    <Modal title="Complete review" onClose={onCancel}>
      <div className="stack">
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Outcome</span>
          <select className="input" value={outcome} onChange={(e) => setOutcome(e.target.value as ComplianceReviewOutcome)} aria-label="Review outcome">
            {OUTCOME_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>{COMPLIANCE_REVIEW_OUTCOME_LABEL[opt]}</option>
            ))}
          </select>
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Notes</span>
          <textarea className="input" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button className="btn btn-primary" onClick={() => onSave({ outcome, notes })}>Complete</button>
        </div>
      </div>
    </Modal>
  );
}
