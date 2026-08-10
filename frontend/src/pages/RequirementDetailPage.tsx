import { GitPullRequest, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, fileUrl } from "../api/client";
import type {
  ChangeEntry,
  Comment,
  CustomFieldDefinition,
  FileAsset,
  OrgUser,
  Project,
  ProjectStage,
  Requirement,
  RequirementLevel,
  RequirementReviewOutcome,
  RequirementVersionEntry,
} from "../api/types";
import { REQUIREMENT_LEVEL_LABEL, REQUIREMENT_STATUS_LABEL } from "../api/types";
import { ActivityPanel } from "../components/ActivityPanel";
import { CommentThread } from "../components/CommentThread";
import { CustomFieldsForm } from "../components/CustomFieldsForm";
import { Spinner } from "../components/Spinner";
import { SubscribeButton } from "../components/SubscribeButton";
import { useAuth } from "../context/AuthContext";
import { useMyProjectRoles } from "../hooks/useMyProjectRoles";
import { t } from "../i18n/strings";

const strings = t();

/**
 * Requirement detail view: direct editing while unlocked, a discussion
 * thread (C-R-01), and a change log that intentionally excludes discussion
 * comments (C-A-09 clarification).
 */
export function RequirementDetailPage() {
  const { projectId, requirementId } = useParams<{ projectId: string; requirementId: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const myRoles = useMyProjectRoles(projectId);
  const canArchive = myRoles.includes("project_manager") || myRoles.includes("project_administrator");
  const canEdit = canArchive || myRoles.includes("stakeholder");
  const [requirement, setRequirement] = useState<Requirement | null>(null);
  const [history, setHistory] = useState<RequirementVersionEntry[]>([]);
  const [comments, setComments] = useState<Comment[]>([]);
  const [form, setForm] = useState({
    name: "",
    reasoning: "",
    clarification: "",
    description: "",
    changeNote: "",
    targetStageId: "",
    level: "requirement" as RequirementLevel,
    reviewDate: "",
    reviewLeadDays: "",
    reviewerId: "",
  });
  const [saveError, setSaveError] = useState<string | null>(null);
  const [files, setFiles] = useState<FileAsset[]>([]);
  const [customFieldDefs, setCustomFieldDefs] = useState<CustomFieldDefinition[]>([]);
  const [customFieldValues, setCustomFieldValues] = useState<Record<string, unknown>>({});
  const [stages, setStages] = useState<ProjectStage[]>([]);
  const [activity, setActivity] = useState<ChangeEntry[]>([]);
  const [reviewOutcome, setReviewOutcome] = useState<RequirementReviewOutcome>("met");
  const [reviewComment, setReviewComment] = useState("");
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [reviewerPickerUnavailable, setReviewerPickerUnavailable] = useState(false);

  function userDisplayName(userId: string | null): string {
    if (!userId) return strings.reviews.unassigned;
    return orgUsers.find((u) => u.user_id === userId)?.display_name ?? userId;
  }

  async function reload() {
    if (!projectId || !requirementId) return;
    const [req, hist, comm, fls, defs, stgs, act] = await Promise.all([
      api.get<Requirement>(`/api/v1/projects/${projectId}/requirements/${requirementId}`),
      api.get<RequirementVersionEntry[]>(`/api/v1/projects/${projectId}/requirements/${requirementId}/history`),
      api.get<Comment[]>(`/api/v1/projects/${projectId}/requirements/${requirementId}/comments`),
      api.get<FileAsset[]>(`/api/v1/projects/${projectId}/requirements/${requirementId}/files`),
      api.get<CustomFieldDefinition[]>(`/api/v1/projects/${projectId}/custom-fields?entity_kind=requirement`),
      api.get<ProjectStage[]>(`/api/v1/projects/${projectId}/stages`),
      api.get<ChangeEntry[]>(`/api/v1/projects/${projectId}/requirements/${requirementId}/activity`),
    ]);
    setRequirement(req);
    setHistory(hist);
    setComments(comm);
    setFiles(fls);
    setCustomFieldDefs(defs);
    setCustomFieldValues(req.custom_fields);
    setStages(stgs);
    setActivity(act);
    setForm({
      name: req.name,
      reasoning: req.reasoning,
      clarification: req.clarification,
      description: req.description,
      changeNote: "",
      targetStageId: req.target_stage_id,
      level: req.level,
      reviewDate: req.review_date ?? "",
      reviewLeadDays: req.review_lead_days != null ? String(req.review_lead_days) : "",
      reviewerId: req.reviewer_id ?? "",
    });
  }

  function stageName(id: string | null) {
    return stages.find((s) => s.id === id)?.name ?? "—";
  }

  async function uploadFile(file: File) {
    await api.postFile(`/api/v1/projects/${projectId}/requirements/${requirementId}/files`, file);
    reload();
  }

  async function removeFile(fileId: string) {
    await api.delete(`/api/v1/projects/${projectId}/requirements/${requirementId}/files/${fileId}`);
    reload();
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, requirementId]);

  useEffect(() => {
    if (!projectId) return;
    (async () => {
      try {
        const project = await api.get<Project>(`/api/v1/projects/${projectId}`);
        const users = await api.get<OrgUser[]>(`/api/v1/orgs/${project.organization_id}/users`);
        setOrgUsers(users);
      } catch {
        // Org member directory isn't reachable for this user (e.g. no org
        // role) — fall back to the plain user-ID input rather than break
        // the page.
        setReviewerPickerUnavailable(true);
      }
    })();
  }, [projectId]);

  async function save() {
    if (!requirement) return;
    setSaveError(null);
    try {
      await api.put(`/api/v1/projects/${projectId}/requirements/${requirementId}`, {
        name: form.name,
        reasoning: form.reasoning,
        clarification: form.clarification,
        description: form.description,
        component_id: requirement.component_id,
        category_id: requirement.category_id,
        owner_id: requirement.owner_id,
        target_stage_id: form.targetStageId,
        level: form.level,
        keywords: requirement.keywords,
        custom_fields: customFieldValues,
        change_note: form.changeNote,
        review_date: form.reviewDate || null,
        review_lead_days: form.reviewLeadDays ? Number(form.reviewLeadDays) : null,
        reviewer_id: form.reviewerId || null,
      });
      reload();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function archive() {
    await api.delete(`/api/v1/projects/${projectId}/requirements/${requirementId}`);
    navigate(`/projects/${projectId}/requirements`);
  }

  async function markCompleted() {
    await api.post(`/api/v1/projects/${projectId}/requirements/${requirementId}/complete`);
    reload();
  }

  async function unmarkCompleted() {
    await api.post(`/api/v1/projects/${projectId}/requirements/${requirementId}/uncomplete`);
    reload();
  }

  async function submitReview() {
    setReviewError(null);
    try {
      await api.post(`/api/v1/projects/${projectId}/requirements/${requirementId}/reviews`, {
        outcome: reviewOutcome,
        comment: reviewComment || null,
      });
      setReviewComment("");
      reload();
    } catch (err) {
      setReviewError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function toggleSubscription() {
    if (!requirement) return;
    if (requirement.is_subscribed) {
      await api.delete(`/api/v1/projects/${projectId}/requirements/${requirementId}/subscription`);
    } else {
      await api.put(`/api/v1/projects/${projectId}/requirements/${requirementId}/subscription`);
    }
    reload();
  }

  async function postComment(body: string): Promise<Comment> {
    const comment = await api.post<Comment>(`/api/v1/projects/${projectId}/requirements/${requirementId}/comments`, { body });
    reload();
    return comment;
  }

  async function editComment(commentId: string, body: string) {
    await api.patch(`/api/v1/projects/${projectId}/requirements/${requirementId}/comments/${commentId}`, { body });
    reload();
  }

  async function removeCommentAttachment(commentId: string, fileId: string) {
    await api.delete(`/api/v1/projects/${projectId}/requirements/${requirementId}/comments/${commentId}/files/${fileId}`);
    reload();
  }

  async function toggleReaction(commentId: string, reacted: boolean) {
    if (reacted) {
      await api.delete(`/api/v1/projects/${projectId}/requirements/${requirementId}/comments/${commentId}/reaction`);
    } else {
      await api.put(`/api/v1/projects/${projectId}/requirements/${requirementId}/comments/${commentId}/reaction`);
    }
    reload();
  }

  async function uploadCommentAttachment(commentId: string, file: File) {
    await api.postFile(`/api/v1/projects/${projectId}/requirements/${requirementId}/comments/${commentId}/files`, file);
    reload();
  }

  if (!requirement) return <Spinner />;

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>
          {requirement.unique_code} — {requirement.name}
        </h1>
        <div className="row">
          <SubscribeButton subscribed={requirement.is_subscribed} onToggle={toggleSubscription} />
          <Link className="btn" to={`/projects/${projectId}/change-requests?requirement=${requirementId}`}>
            <GitPullRequest size={14} /> {strings.requirements.makeChangeRequest}
          </Link>
          {canArchive && requirement.status === "approved" && (
            <button className="btn" onClick={markCompleted}>
              {strings.requirements.markCompleted}
            </button>
          )}
          {canArchive && requirement.status === "completed" && (
            <button className="btn" onClick={unmarkCompleted}>
              {strings.requirements.unmarkCompleted}
            </button>
          )}
          {canArchive && (
            <button className="btn btn-danger" onClick={archive}>
              {strings.requirements.archive}
            </button>
          )}
        </div>
      </div>

      <div className="side-grid">
      <div className="stack">
      {requirement.is_locked || !canEdit ? (
        <div className="card stack">
          {requirement.is_locked && (
            <div className="badge" style={{ alignSelf: "flex-start" }}>
              {strings.requirements.locked} — {strings.requirements.lockedNotice}
            </div>
          )}
          <div>
            <div className="text-muted">{strings.requirements.reasoning}</div>
            <p style={{ marginTop: "0.25rem" }}>{requirement.reasoning}</p>
          </div>
          {requirement.clarification && (
            <div>
              <div className="text-muted">{strings.requirements.clarification}</div>
              <p style={{ marginTop: "0.25rem" }}>{requirement.clarification}</p>
            </div>
          )}
          {requirement.description && (
            <div>
              <div className="text-muted">{strings.requirements.description}</div>
              <p style={{ marginTop: "0.25rem" }}>{requirement.description}</p>
            </div>
          )}
          <div className="row">
            <span className="badge">{strings.requirements.status}: {REQUIREMENT_STATUS_LABEL[requirement.status]}</span>
            <span className="badge">Target: {stageName(requirement.target_stage_id)}</span>
            <span className="badge">Level: {REQUIREMENT_LEVEL_LABEL[requirement.level]}</span>
            {requirement.review_date && <span className="badge">{strings.requirements.reviewDate}: {requirement.review_date}</span>}
            {requirement.keywords.map((k) => (
              <span key={k} className="badge">
                {k}
              </span>
            ))}
          </div>
          <CustomFieldsForm definitions={customFieldDefs} values={customFieldValues} disabled onChange={() => {}} />
        </div>
      ) : (
        <div className="card stack">
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.requirements.name}
            <input className="input" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
          </label>
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.requirements.reasoning}
            <textarea
              className="input"
              rows={3}
              value={form.reasoning}
              onChange={(e) => setForm((f) => ({ ...f, reasoning: e.target.value }))}
            />
          </label>
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.requirements.clarification}
            <textarea
              className="input"
              rows={2}
              value={form.clarification}
              onChange={(e) => setForm((f) => ({ ...f, clarification: e.target.value }))}
            />
          </label>
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.requirements.description}
            <textarea
              className="input"
              rows={2}
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            />
          </label>
          <div className="row">
            <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
              {strings.requirements.targetVersion}
              <select
                className="input"
                value={form.targetStageId}
                onChange={(e) => setForm((f) => ({ ...f, targetStageId: e.target.value }))}
              >
                {stages.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
              {strings.requirements.level}
              <select
                className="input"
                value={form.level}
                onChange={(e) => setForm((f) => ({ ...f, level: e.target.value as RequirementLevel }))}
              >
                <option value="requirement">{REQUIREMENT_LEVEL_LABEL.requirement}</option>
                <option value="recommended">{REQUIREMENT_LEVEL_LABEL.recommended}</option>
                <option value="optional">{REQUIREMENT_LEVEL_LABEL.optional}</option>
              </select>
            </label>
          </div>
          <div className="row">
            <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
              {strings.requirements.reviewDate}
              <input
                className="input" type="date" value={form.reviewDate}
                onChange={(e) => setForm((f) => ({ ...f, reviewDate: e.target.value }))}
              />
            </label>
            <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
              {strings.requirements.reviewLeadDays}
              <input
                className="input" type="number" min={0} value={form.reviewLeadDays}
                onChange={(e) => setForm((f) => ({ ...f, reviewLeadDays: e.target.value }))}
              />
            </label>
            <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
              {strings.requirements.reviewer}
              {reviewerPickerUnavailable ? (
                <input
                  className="input" placeholder={strings.admin.userId} value={form.reviewerId}
                  onChange={(e) => setForm((f) => ({ ...f, reviewerId: e.target.value }))}
                />
              ) : (
                <select
                  className="input" value={form.reviewerId}
                  onChange={(e) => setForm((f) => ({ ...f, reviewerId: e.target.value }))}
                >
                  <option value="">{strings.reviews.unassigned}</option>
                  {orgUsers.map((u) => (
                    <option key={u.user_id} value={u.user_id}>
                      {u.display_name} ({u.email})
                    </option>
                  ))}
                  {form.reviewerId && !orgUsers.some((u) => u.user_id === form.reviewerId) && (
                    <option value={form.reviewerId}>
                      {form.reviewerId} ({strings.requirements.reviewerNoLongerMember})
                    </option>
                  )}
                </select>
              )}
            </label>
          </div>
          <CustomFieldsForm
            definitions={customFieldDefs}
            values={customFieldValues}
            onChange={(fieldId, value) => setCustomFieldValues((v) => ({ ...v, [fieldId]: value }))}
          />
          <input
            className="input"
            placeholder={strings.requirements.changeNote}
            value={form.changeNote}
            onChange={(e) => setForm((f) => ({ ...f, changeNote: e.target.value }))}
          />
          {saveError && <div style={{ color: "var(--color-danger)" }}>{saveError}</div>}
          <button className="btn btn-primary" onClick={save} style={{ alignSelf: "flex-start" }}>
            {strings.requirements.save}
          </button>
        </div>
      )}

      {requirement.review_date && (
        <div className="card stack">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.requirements.reviewSection}</h2>
          <div className="row">
            <span className="badge">{strings.requirements.reviewDate}: {requirement.review_date}</span>
            <span className="badge">{strings.requirements.reviewer}: {userDisplayName(requirement.reviewer_id)}</span>
          </div>
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.requirements.recordReviewOutcome}
            <select
              className="input" value={reviewOutcome}
              onChange={(e) => setReviewOutcome(e.target.value as RequirementReviewOutcome)}
            >
              <option value="met">{strings.requirements.reviewOutcomeMet}</option>
              <option value="failed">{strings.requirements.reviewOutcomeFailed}</option>
            </select>
          </label>
          {reviewOutcome === "failed" && (
            <label className="stack" style={{ gap: "0.25rem" }}>
              {strings.requirements.reviewComment}
              <textarea
                className="input" rows={2} value={reviewComment}
                onChange={(e) => setReviewComment(e.target.value)}
              />
            </label>
          )}
          {reviewError && <div style={{ color: "var(--color-danger)" }}>{reviewError}</div>}
          <button className="btn btn-primary" onClick={submitReview} style={{ alignSelf: "flex-start" }}>
            {strings.requirements.submitReview}
          </button>
        </div>
      )}

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.requirements.history}</h2>
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>{strings.requirements.status}</th>
              <th>{strings.requirements.changeNote}</th>
              <th>{strings.requirements.changedBy}</th>
              <th>{strings.requirements.when}</th>
            </tr>
          </thead>
          <tbody>
            {history.map((h) => (
              <tr key={h.version_number}>
                <td>{h.version_number}</td>
                <td>{h.status}</td>
                <td>{h.change_note}</td>
                <td>{userDisplayName(h.created_by)}</td>
                <td>{new Date(h.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.requirements.attachments}</h2>
        {files.map((f) => (
          <div key={f.id} className="row" style={{ justifyContent: "space-between" }}>
            <a href={fileUrl(f.id)} target="_blank" rel="noreferrer">
              {f.filename}
            </a>
            <button className="btn btn-danger" onClick={() => removeFile(f.id)}>
              <Trash2 size={14} />
            </button>
          </div>
        ))}
        {requirement.is_locked ? (
          <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
            {strings.requirements.attachmentsLockedNotice}
          </p>
        ) : (
          <input type="file" onChange={(e) => e.target.files?.[0] && uploadFile(e.target.files[0])} />
        )}
      </div>

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.requirements.discussion}</h2>
        <CommentThread
          comments={comments}
          onPost={postComment}
          onToggleReaction={toggleReaction}
          onUploadAttachment={uploadCommentAttachment}
          onRemoveAttachment={removeCommentAttachment}
          onEdit={editComment}
          currentUserId={user?.id}
        />
      </div>
      </div>

      <ActivityPanel entries={activity} />
      </div>
    </div>
  );
}
