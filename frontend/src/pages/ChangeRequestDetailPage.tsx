import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import type { ChangeRequest, Comment } from "../api/types";
import { Spinner } from "../components/Spinner";
import { t } from "../i18n/strings";

const strings = t();

/** Change request detail: submit/withdraw/decide and its discussion thread (C-R-01). */
export function ChangeRequestDetailPage() {
  const { projectId, crId } = useParams<{ projectId: string; crId: string }>();
  const [cr, setCr] = useState<ChangeRequest | null>(null);
  const [comments, setComments] = useState<Comment[]>([]);
  const [newComment, setNewComment] = useState("");
  const [decisionNote, setDecisionNote] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);

  async function reload() {
    if (!projectId || !crId) return;
    const [crData, commentData] = await Promise.all([
      api.get<ChangeRequest>(`/api/v1/projects/${projectId}/change-requests/${crId}`),
      api.get<Comment[]>(`/api/v1/projects/${projectId}/change-requests/${crId}/comments`),
    ]);
    setCr(crData);
    setComments(commentData);
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

  async function postComment() {
    if (!newComment.trim()) return;
    await api.post(`/api/v1/projects/${projectId}/change-requests/${crId}/comments`, { body: newComment });
    setNewComment("");
    reload();
  }

  if (!cr) return <Spinner />;

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>{cr.proposed_name}</h1>
      <div className="card stack">
        <div>
          <span className="badge">{cr.status}</span>
        </div>
        <p>
          <strong>Reasoning:</strong> {cr.proposed_reasoning}
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
        {comments.map((c) => (
          <div key={c.id} className="card">
            <div className="text-muted" style={{ fontSize: "0.8rem" }}>
              {new Date(c.created_at).toLocaleString()}
            </div>
            <div>{c.body}</div>
          </div>
        ))}
        <div className="row">
          <input
            className="input"
            placeholder={strings.requirements.addComment}
            value={newComment}
            onChange={(e) => setNewComment(e.target.value)}
          />
          <button className="btn" onClick={postComment}>
            {strings.requirements.addComment}
          </button>
        </div>
      </div>
    </div>
  );
}
