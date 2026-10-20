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
import { useState } from "react";

import type { OrgUser, PrincipalRef } from "../../api/types";
import { principalRef, savedPrincipalDisplay } from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { Modal } from "../../components/Modal";
import { PrincipalBadge } from "../../components/PrincipalBadge";
import { PrincipalFormField } from "../../components/PrincipalFormField";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import {
  COMPLIANCE_REVIEW_OUTCOME_LABEL,
  COMPLIANCE_REVIEW_SCHEDULE_STATE_LABEL,
  COMPLIANCE_REVIEW_STATUS_LABEL,
  type ComplianceReview,
  type ComplianceReviewOutcome,
} from "./types";
import { Badge } from "../../components/Badge";
import { DateField, TextAreaField, TextField } from "../../components/FormFields";
import { FormActions } from "../../components/FormActions";
import { LabeledSelect } from "../../components/LabeledSelect";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { COMPLIANCE_HELP } from "./help";

export function ReviewsPanel({
  projectId, projectComplianceId, organizationId, orgUsers,
}: { projectId: string; projectComplianceId: string; organizationId: string; orgUsers: OrgUser[] }) {
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

  useLoadOnChange(reload, [projectId, projectComplianceId]);

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
                  {r.schedule_state && <Badge className="badge-after">{COMPLIANCE_REVIEW_SCHEDULE_STATE_LABEL[r.schedule_state]}</Badge>}
                  <Badge className="badge-after">{COMPLIANCE_REVIEW_STATUS_LABEL[r.status]}</Badge>
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
              <div className="row" style={{ gap: "0.5rem", alignItems: "center", fontSize: "0.85rem" }}>
                <span className="text-muted">Owner:</span>
                <PrincipalBadge principal={r.owner} />
                {r.notes && <span className="text-muted">— {r.notes}</span>}
              </div>
            </li>
          ))}
        </ul>
      )}

      {(creating || editing) && (
        <ReviewFormModal
          initial={editing ?? undefined}
          orgUsers={orgUsers}
          organizationId={organizationId}
          projectId={projectId}
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
  organizationId,
  projectId,
  onCancel,
  onSave,
}: {
  initial?: ComplianceReview;
  orgUsers: OrgUser[];
  organizationId: string;
  projectId: string;
  onCancel: () => void;
  onSave: (values: { frequency_label: string; recurrence_days: number | null; next_due_date: string; owner: PrincipalRef | null; notes: string }) => void;
}) {
  const [frequencyLabel, setFrequencyLabel] = useState(initial?.frequency_label ?? "");
  const [recurrenceDays, setRecurrenceDays] = useState(initial?.recurrence_days ? String(initial.recurrence_days) : "");
  const [nextDueDate, setNextDueDate] = useState(initial?.next_due_date ?? "");
  const [owner, setOwner] = useState<PrincipalRef | null>(principalRef(initial?.owner));
  const [notes, setNotes] = useState(initial?.notes ?? "");

  return (
    <Modal title={initial ? "Edit review" : "Schedule review"} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <FormGridFull>
            <TextField helpNotNeeded required
              label="Frequency / description"
              ariaLabel="Frequency label"
              value={frequencyLabel}
              onChange={setFrequencyLabel}
              placeholder="e.g. Annual security review"
            />
          </FormGridFull>
          <DateField helpNotNeeded required label="Next due date" value={nextDueDate} onChange={setNextDueDate} />
          <TextField help={COMPLIANCE_HELP.complianceReviewRecurrence}
            label="Recurs every (days)"
            value={recurrenceDays}
            onChange={setRecurrenceDays}
            inputProps={{ min: 1, type: "number" }}
          />
          <FormGridFull>
            <PrincipalFormField helpNotNeeded
              label="Owner" orgUsers={orgUsers} organizationId={organizationId} projectId={projectId}
              value={owner} display={savedPrincipalDisplay(owner, initial?.owner)} onChange={setOwner} ariaLabel="Review owner"
            />
          </FormGridFull>
          <FormGridFull>
            <TextAreaField helpNotNeeded label="Notes" value={notes} onChange={setNotes} rows={2} />
          </FormGridFull>
        </FormGrid>
        <FormActions
          onCancel={onCancel}
          onSave={() =>
            onSave({
              frequency_label: frequencyLabel, recurrence_days: recurrenceDays ? Number(recurrenceDays) : null,
              next_due_date: nextDueDate, owner, notes,
            })}
          saveDisabled={!frequencyLabel.trim() || !nextDueDate}
        />
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
        <LabeledSelect helpNotNeeded
          label="Outcome"
          ariaLabel="Review outcome"
          value={outcome}
          onChange={(next) => setOutcome(next as ComplianceReviewOutcome)}
          options={OUTCOME_OPTIONS.map((opt) => ({ value: opt, label: COMPLIANCE_REVIEW_OUTCOME_LABEL[opt] }))}
          placeholder={null}
        />
        <TextAreaField helpNotNeeded label="Notes" value={notes} onChange={setNotes} rows={2} />
        <FormActions onCancel={onCancel} onSave={() => onSave({ outcome, notes })} saveLabel="Complete" />
      </div>
    </Modal>
  );
}
