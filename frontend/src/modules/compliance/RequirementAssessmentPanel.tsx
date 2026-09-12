/**
 * Module: modules/compliance/RequirementAssessmentPanel
 *
 * The per-requirement detail workspace opened from `ApplicabilityTree` (a
 * `SidePanel`, per style guide "Pattern: entity detail panel" — viewing an
 * existing entity's full detail without leaving the tree behind it, never a
 * `Modal`). Covers §21's own drill-down diagram for one requirement:
 * Applicability (§9), Assessment (§10, §16), Required Actions (§6),
 * Evidence (§13), Approval/Sign-off (§12), and history (§8/§11/§16 — "view
 * compliance history").
 *
 * Mandatory-justification rules are enforced here purely as a UX
 * convenience (disabling Save until filled) — the backend is the actual
 * enforcement (`project_router.py::update_requirement_applicability`/
 * `update_requirement_assessment`, 400 on a missing justification), so a
 * stale client check can never let a bad payload through undetected: any
 * 400 still surfaces as a toast either way.
 */
import { useEffect, useState } from "react";

import type { OrgUser } from "../../api/types";
import { activityActionLabel } from "../../api/types";
import { AssigneePicker } from "../../components/AssigneePicker";
import { Modal } from "../../components/Modal";
import { SidePanel } from "../../components/SidePanel";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import { ApplicabilityBadge } from "./ApplicabilityBadge";
import {
  COMPLIANCE_APPLICABILITY_LABEL,
  COMPLIANCE_APPROVAL_STATE_LABEL,
  COMPLIANCE_STATUS_LABEL,
  type ComplianceApplicability,
  type ComplianceAuditEvent,
  type ComplianceEvidence,
  type ComplianceRequiredAction,
  type ComplianceRequiredActionAssessment,
  type ComplianceRequirementNode,
  type ComplianceStatus,
  type ProjectComplianceRequirement,
  userDisplayName,
} from "./types";

const APPLICABILITY_OPTIONS: ComplianceApplicability[] = ["applicable", "not_applicable"];
const STATUS_OPTIONS: ComplianceStatus[] = [
  "not_started", "in_progress", "compliant", "non_compliant", "blocked", "pending_review", "rejected",
];

export function RequirementAssessmentPanel({
  orgId,
  projectId,
  standardId,
  versionId,
  projectComplianceId,
  requirement,
  pcr,
  orgUsers,
  onClose,
  onChanged,
}: {
  orgId: string;
  projectId: string;
  standardId: string;
  versionId: string;
  projectComplianceId: string;
  requirement: ComplianceRequirementNode;
  pcr: ProjectComplianceRequirement;
  orgUsers: OrgUser[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const { showToast } = useToast();

  const [applicability, setApplicability] = useState<ComplianceApplicability>(pcr.explicit_applicability ?? "applicable");
  const [applicabilityJustification, setApplicabilityJustification] = useState(pcr.justification);
  const [status, setStatus] = useState<ComplianceStatus>(pcr.compliance_status);
  const [statusJustification, setStatusJustification] = useState(pcr.justification);
  const [notes, setNotes] = useState(pcr.notes);
  const [decisionNote, setDecisionNote] = useState("");
  const [rejecting, setRejecting] = useState(false);

  const [actionDefs, setActionDefs] = useState<ComplianceRequiredAction[] | null>(null);
  const [assessments, setAssessments] = useState<ComplianceRequiredActionAssessment[] | null>(null);
  const [linkedEvidence, setLinkedEvidence] = useState<ComplianceEvidence[] | null>(null);
  const [allEvidence, setAllEvidence] = useState<ComplianceEvidence[] | null>(null);
  const [linkEvidenceId, setLinkEvidenceId] = useState("");
  const [history, setHistory] = useState<ComplianceAuditEvent[] | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  async function reloadRequiredActions() {
    const [defs, rows] = await Promise.all([
      complianceApi.listRequiredActions(orgId, standardId, versionId, requirement.id),
      complianceApi.listRequiredActionAssessments(projectId, projectComplianceId, pcr.id),
    ]);
    setActionDefs(defs);
    setAssessments(rows);
  }

  async function reloadEvidence() {
    const [linked, all] = await Promise.all([
      complianceApi.listRequirementEvidence(projectId, projectComplianceId, pcr.id),
      complianceApi.listEvidence(projectId),
    ]);
    setLinkedEvidence(linked);
    setAllEvidence(all.filter((e) => !e.is_archived));
  }

  useEffect(() => {
    setApplicability(pcr.explicit_applicability ?? "applicable");
    setApplicabilityJustification(pcr.justification);
    setStatus(pcr.compliance_status);
    setStatusJustification(pcr.justification);
    setNotes(pcr.notes);
    setDecisionNote("");
    reloadRequiredActions().catch((err) => showToast(toErrorMessage(err, "Could not load required actions."), "error"));
    reloadEvidence().catch((err) => showToast(toErrorMessage(err, "Could not load evidence."), "error"));
    setHistory(null);
    setShowHistory(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pcr.id]);

  async function loadHistory() {
    setShowHistory(true);
    if (history !== null) return;
    try {
      setHistory(await complianceApi.getRequirementHistory(projectId, projectComplianceId, pcr.id));
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load history."), "error");
    }
  }

  async function saveApplicability() {
    try {
      await complianceApi.updateRequirementApplicability(projectId, projectComplianceId, pcr.id, {
        applicability, justification: applicabilityJustification,
      });
      showToast("Applicability updated.");
      onChanged();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update applicability."), "error");
    }
  }

  async function saveAssessment() {
    try {
      await complianceApi.updateRequirementAssessment(projectId, projectComplianceId, pcr.id, {
        compliance_status: status, justification: statusJustification, notes,
      });
      showToast("Assessment updated.");
      onChanged();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update assessment."), "error");
    }
  }

  async function submitForApproval() {
    try {
      await complianceApi.submitRequirementForApproval(projectId, projectComplianceId, pcr.id);
      showToast("Submitted for approval.");
      onChanged();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not submit for approval."), "error");
    }
  }

  async function approve() {
    try {
      await complianceApi.approveRequirement(projectId, projectComplianceId, pcr.id, decisionNote);
      showToast("Approved.");
      setDecisionNote("");
      onChanged();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not approve."), "error");
    }
  }

  async function reject() {
    try {
      await complianceApi.rejectRequirement(projectId, projectComplianceId, pcr.id, decisionNote);
      showToast("Rejected.");
      setDecisionNote("");
      setRejecting(false);
      onChanged();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not reject."), "error");
    }
  }

  async function toggleActionComplete(assessment: ComplianceRequiredActionAssessment) {
    try {
      if (assessment.is_completed) {
        await complianceApi.uncompleteRequiredActionAssessment(projectId, projectComplianceId, pcr.id, assessment.id);
      } else {
        await complianceApi.completeRequiredActionAssessment(projectId, projectComplianceId, pcr.id, assessment.id);
      }
      await reloadRequiredActions();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update required action."), "error");
    }
  }

  async function updateActionAssignee(assessment: ComplianceRequiredActionAssessment, assigneeId: string) {
    try {
      await complianceApi.updateRequiredActionAssessment(projectId, projectComplianceId, pcr.id, assessment.id, {
        assignee_id: assigneeId || null, due_date: assessment.due_date, notes: assessment.notes,
      });
      await reloadRequiredActions();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update assignee."), "error");
    }
  }

  async function updateActionDueDate(assessment: ComplianceRequiredActionAssessment, dueDate: string) {
    try {
      await complianceApi.updateRequiredActionAssessment(projectId, projectComplianceId, pcr.id, assessment.id, {
        assignee_id: assessment.assignee_id, due_date: dueDate || null, notes: assessment.notes,
      });
      await reloadRequiredActions();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update due date."), "error");
    }
  }

  async function linkEvidence() {
    if (!linkEvidenceId) return;
    try {
      await complianceApi.linkEvidenceToRequirement(projectId, linkEvidenceId, pcr.id);
      setLinkEvidenceId("");
      showToast("Evidence linked.");
      await reloadEvidence();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not link evidence."), "error");
    }
  }

  async function unlinkEvidence(evidenceId: string) {
    try {
      await complianceApi.unlinkEvidenceFromRequirement(projectId, evidenceId, pcr.id);
      showToast("Evidence unlinked.");
      await reloadEvidence();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not unlink evidence."), "error");
    }
  }

  const linkableEvidence = (allEvidence ?? []).filter(
    (e) => !(linkedEvidence ?? []).some((linked) => linked.id === e.id)
  );

  return (
    <SidePanel
      title={`${requirement.reference ? `${requirement.reference} — ` : ""}${requirement.name}`}
      onClose={onClose}
    >
      <div className="stack">
        {requirement.description && <p className="text-muted" style={{ margin: 0 }}>{requirement.description}</p>}

        <section className="stack">
          <h3 style={{ margin: 0 }}>Applicability</h3>
          <div className="row" style={{ alignItems: "center", gap: "0.5rem" }}>
            <span>Effective:</span>
            <ApplicabilityBadge pcr={pcr} />
          </div>
          <label className="stack" style={{ gap: "0.25rem" }}>
            <span>Set applicability</span>
            <select className="input" value={applicability} onChange={(e) => setApplicability(e.target.value as ComplianceApplicability)} aria-label="Applicability">
              {APPLICABILITY_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>{COMPLIANCE_APPLICABILITY_LABEL[opt]}</option>
              ))}
            </select>
          </label>
          {applicability === "not_applicable" && (
            <label className="stack" style={{ gap: "0.25rem" }}>
              <span>Justification (required)</span>
              <textarea className="input" rows={2} value={applicabilityJustification} onChange={(e) => setApplicabilityJustification(e.target.value)} />
            </label>
          )}
          <button
            className="btn btn-primary" style={{ alignSelf: "flex-start" }}
            disabled={applicability === "not_applicable" && !applicabilityJustification.trim()}
            onClick={saveApplicability}
          >
            Update applicability
          </button>
        </section>

        {pcr.effective_applicability === "applicable" && (
          <section className="stack">
            <h3 style={{ margin: 0 }}>Assessment</h3>
            <label className="stack" style={{ gap: "0.25rem" }}>
              <span>Compliance status</span>
              <select className="input" value={status} onChange={(e) => setStatus(e.target.value as ComplianceStatus)} aria-label="Compliance status">
                {STATUS_OPTIONS.map((opt) => (
                  <option key={opt} value={opt}>{COMPLIANCE_STATUS_LABEL[opt]}</option>
                ))}
              </select>
            </label>
            {status === "non_compliant" && (
              <label className="stack" style={{ gap: "0.25rem" }}>
                <span>Justification (required)</span>
                <textarea className="input" rows={2} value={statusJustification} onChange={(e) => setStatusJustification(e.target.value)} />
              </label>
            )}
            <label className="stack" style={{ gap: "0.25rem" }}>
              <span>Notes</span>
              <textarea className="input" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
            </label>
            <button
              className="btn btn-primary" style={{ alignSelf: "flex-start" }}
              disabled={status === "non_compliant" && !statusJustification.trim()}
              onClick={saveAssessment}
            >
              Update assessment
            </button>
            {pcr.assessed_at && (
              <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
                Last assessed {new Date(pcr.assessed_at).toLocaleString()} by {userDisplayName(orgUsers, pcr.assessed_by)}
              </p>
            )}
          </section>
        )}

        <section className="stack">
          <h3 style={{ margin: 0 }}>Required actions</h3>
          {actionDefs === null || assessments === null ? (
            <Spinner />
          ) : assessments.length === 0 ? (
            <p className="text-muted" style={{ margin: 0 }}>No required actions for this requirement.</p>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {assessments.map((assessment) => {
                const def = actionDefs.find((d) => d.id === assessment.required_action_id);
                return (
                  <li key={assessment.id} className="stack" style={{ borderBottom: "1px solid var(--color-border)", padding: "0.4rem 0" }}>
                    <div className="row" style={{ justifyContent: "space-between" }}>
                      <span>
                        {def?.name ?? "Required action"}
                        {def?.is_mandatory && <span className="text-muted"> (mandatory)</span>}
                      </span>
                      <label className="row" style={{ gap: "0.3rem" }}>
                        <input type="checkbox" checked={assessment.is_completed} onChange={() => toggleActionComplete(assessment)} />
                        Completed
                      </label>
                    </div>
                    <div className="row" style={{ gap: "0.5rem", flexWrap: "wrap" }}>
                      <div className="stack" style={{ gap: "0.2rem" }}>
                        <span className="text-muted" style={{ fontSize: "0.8rem" }}>Assignee</span>
                        <AssigneePicker
                          orgUsers={orgUsers}
                          organizationId={orgId}
                          assigneeId={assessment.assignee_id}
                          onChange={(userId) => updateActionAssignee(assessment, userId)}
                          ariaLabel={`Assignee for ${def?.name ?? "required action"}`}
                        />
                      </div>
                      <label className="row" style={{ gap: "0.3rem" }}>
                        <span className="text-muted" style={{ fontSize: "0.8rem" }}>Due date</span>
                        <input
                          className="input" type="date" value={assessment.due_date ?? ""}
                          onChange={(e) => updateActionDueDate(assessment, e.target.value)}
                          aria-label={`Due date for ${def?.name ?? "required action"}`}
                        />
                      </label>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section className="stack">
          <h3 style={{ margin: 0 }}>Evidence</h3>
          {linkedEvidence === null ? (
            <Spinner />
          ) : linkedEvidence.length === 0 ? (
            <p className="text-muted" style={{ margin: 0 }}>No evidence linked yet.</p>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {linkedEvidence.map((e) => (
                <li key={e.id} className="row" style={{ justifyContent: "space-between", padding: "0.25rem 0" }}>
                  <span>{e.title}</span>
                  <button className="btn btn-danger" onClick={() => unlinkEvidence(e.id)} aria-label={`Unlink ${e.title}`}>Unlink</button>
                </li>
              ))}
            </ul>
          )}
          {linkableEvidence.length > 0 && (
            <div className="row" style={{ gap: "0.5rem" }}>
              <select className="input" value={linkEvidenceId} onChange={(e) => setLinkEvidenceId(e.target.value)} aria-label="Link existing evidence">
                <option value="">Select evidence to link…</option>
                {linkableEvidence.map((e) => (
                  <option key={e.id} value={e.id}>{e.title}</option>
                ))}
              </select>
              <button className="btn" disabled={!linkEvidenceId} onClick={linkEvidence}>Link</button>
            </div>
          )}
        </section>

        <section className="stack">
          <h3 style={{ margin: 0 }}>Approval / sign-off</h3>
          <p style={{ margin: 0 }}>Current state: <strong>{COMPLIANCE_APPROVAL_STATE_LABEL[pcr.approval_state]}</strong></p>
          {pcr.approval_state === "assessed" && (
            <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={submitForApproval}>
              Submit for approval
            </button>
          )}
          {pcr.approval_state === "pending_approval" && (
            <div className="stack">
              <label className="stack" style={{ gap: "0.25rem" }}>
                <span>Decision note (optional for approval, required to reject)</span>
                <textarea className="input" rows={2} value={decisionNote} onChange={(e) => setDecisionNote(e.target.value)} />
              </label>
              <div className="row">
                <button className="btn btn-primary" onClick={approve}>Approve</button>
                <button className="btn btn-danger" onClick={() => setRejecting(true)}>Reject</button>
              </div>
            </div>
          )}
          {pcr.approval_decided_at && (
            <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
              Decided {new Date(pcr.approval_decided_at).toLocaleString()} by {userDisplayName(orgUsers, pcr.approval_decided_by)}
              {pcr.decision_note && ` — "${pcr.decision_note}"`}
            </p>
          )}
        </section>

        <section className="stack">
          <button className="btn" style={{ alignSelf: "flex-start" }} onClick={loadHistory}>
            {showHistory ? "Refresh history" : "Show history"}
          </button>
          {showHistory && (
            history === null ? (
              <Spinner />
            ) : history.length === 0 ? (
              <p className="text-muted" style={{ margin: 0 }}>No history yet.</p>
            ) : (
              <ul style={{ listStyle: "none", margin: 0, padding: 0, fontSize: "0.85rem" }}>
                {history.map((h) => (
                  <li key={h.id} style={{ borderBottom: "1px solid var(--color-border)", padding: "0.3rem 0" }}>
                    <span className="text-muted">{new Date(h.created_at).toLocaleString()}</span>{" "}
                    — {userDisplayName(orgUsers, h.actor_id)} — {activityActionLabel(h.action)}
                  </li>
                ))}
              </ul>
            )
          )}
        </section>
      </div>

      {rejecting && (
        <Modal title="Reject this assessment?" onClose={() => setRejecting(false)}>
          <div className="stack">
            <label className="stack" style={{ gap: "0.25rem" }}>
              <span>Decision note (required)</span>
              <textarea className="input" rows={3} value={decisionNote} onChange={(e) => setDecisionNote(e.target.value)} />
            </label>
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button className="btn" onClick={() => setRejecting(false)}>Cancel</button>
              <button className="btn btn-danger" disabled={!decisionNote.trim()} onClick={reject}>Reject</button>
            </div>
          </div>
        </Modal>
      )}
    </SidePanel>
  );
}
