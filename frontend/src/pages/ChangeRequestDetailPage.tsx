import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import type { ChangeEntry, ChangeRequest, Comment, ProjectStage } from "../api/types";
import { ActivityPanel } from "../components/ActivityPanel";
import { CommentThread } from "../components/CommentThread";
import { Spinner } from "../components/Spinner";
import { SubscribeButton } from "../components/SubscribeButton";
import { t } from "../i18n/strings";

const strings = t();

/** Change request detail: submit/withdraw/decide and its discussion thread (C-R-01). */
export function ChangeRequestDetailPage() {
  const { projectId, crId } = useParams<{ projectId: string; crId: string }>();
  const [cr, setCr] = useState<ChangeRequest | null>(null);
  const [comments, setComments] = useState<Comment[]>([]);
  const [decisionNote, setDecisionNote] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [stages, setStages] = useState<ProjectStage[]>([]);
  const [activity, setActivity] = useState<ChangeEntry[]>([]);

  async function reload() {
    if (!projectId || !crId) return;
    const [crData, commentData, stageData, activityData] = await Promise.all([
      api.get<ChangeRequest>(`/api/v1/projects/${projectId}/change-requests/${crId}`),
      api.get<Comment[]>(`/api/v1/projects/${projectId}/change-requests/${crId}/comments`),
      api.get<ProjectStage[]>(`/api/v1/projects/${projectId}/stages`),
      api.get<ChangeEntry[]>(`/api/v1/projects/${projectId}/change-requests/${crId}/activity`),
    ]);
    setCr(crData);
    setComments(commentData);
    setStages(stageData);
    setActivity(activityData);
  }

  function stageName(id: string | null) {
    return stages.find((s) => s.id === id)?.name ?? "—";
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, crId]);

  async function act(action: () => Promise<unknown>) {
    setActionError(null);
    try {
      await action();
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function postComment(body: string) {
    await api.post(`/api/v1/projects/${projectId}/change-requests/${crId}/comments`, { body });
    reload();
  }

  async function toggleReaction(commentId: string, reacted: boolean) {
    if (reacted) {
      await api.delete(`/api/v1/projects/${projectId}/change-requests/${crId}/comments/${commentId}/reaction`);
    } else {
      await api.put(`/api/v1/projects/${projectId}/change-requests/${crId}/comments/${commentId}/reaction`);
    }
    reload();
  }

  async function toggleSubscription() {
    if (!cr) return;
    if (cr.is_subscribed) {
      await api.delete(`/api/v1/projects/${projectId}/change-requests/${crId}/subscription`);
    } else {
      await api.put(`/api/v1/projects/${projectId}/change-requests/${crId}/subscription`);
    }
    reload();
  }

  if (!cr) return <Spinner />;

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>{cr.proposed_name}</h1>
        <SubscribeButton subscribed={cr.is_subscribed} onToggle={toggleSubscription} />
      </div>
      <div className="grid" style={{ gridTemplateColumns: "1fr 240px", alignItems: "start", gap: "1rem" }}>
      <div className="stack">
      <div className="card stack">
        <div className="row">
          <span className="badge">{cr.status}</span>
          <span className="badge">Target: {stageName(cr.proposed_target_stage_id)}</span>
          <span className="badge">Level: {cr.proposed_level}</span>
        </div>
        <p>
          <strong>{strings.requirements.reasoning}:</strong> {cr.proposed_reasoning}
        </p>
        <p>
          <strong>{strings.changeRequests.reason}:</strong> {cr.reason}
        </p>
        {cr.decision_note && (
          <p>
            <strong>{strings.changeRequests.decisionNote}:</strong> {cr.decision_note}
          </p>
        )}
        {actionError && <div style={{ color: "var(--color-danger)" }}>{actionError}</div>}
        <div className="row">
          {cr.status === "draft" && (
            <button
              className="btn btn-primary"
              onClick={() => act(() => api.post(`/api/v1/projects/${projectId}/change-requests/${crId}/submit`))}
            >
              {strings.changeRequests.submit}
            </button>
          )}
          {(cr.status === "draft" || cr.status === "submitted") && (
            <button
              className="btn"
              onClick={() => act(() => api.post(`/api/v1/projects/${projectId}/change-requests/${crId}/withdraw`))}
            >
              {strings.changeRequests.withdraw}
            </button>
          )}
          {(cr.status === "submitted" || cr.status === "in_review") && (
            <>
              <input
                className="input"
                style={{ maxWidth: 240 }}
                placeholder={strings.changeRequests.decisionNote}
                value={decisionNote}
                onChange={(e) => setDecisionNote(e.target.value)}
              />
              <button
                className="btn btn-primary"
                onClick={() =>
                  act(() =>
                    api.post(`/api/v1/projects/${projectId}/change-requests/${crId}/decide`, {
                      approve: true,
                      note: decisionNote,
                    })
                  )
                }
              >
                {strings.changeRequests.approve}
              </button>
              <button
                className="btn btn-danger"
                onClick={() =>
                  act(() =>
                    api.post(`/api/v1/projects/${projectId}/change-requests/${crId}/decide`, {
                      approve: false,
                      note: decisionNote,
                    })
                  )
                }
              >
                {strings.changeRequests.reject}
              </button>
            </>
          )}
        </div>
      </div>

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.requirements.discussion}</h2>
        <CommentThread comments={comments} onPost={postComment} onToggleReaction={toggleReaction} />
      </div>
      </div>

      <ActivityPanel entries={activity} />
      </div>
    </div>
  );
}
