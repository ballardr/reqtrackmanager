/**
 * Module: components/RecordCommentsCards
 *
 * The generic comment cards of a record page whose type opted in to record comments: the record's own comments (the shared
 * `ArtefactCommentsSection`) and, below it, the pinned threads on drawings that are anchored to this record (a box or a
 * line), read-only, each linking to its drawing with the thread open.
 *
 * Responsibilities:
 * - Wire `ArtefactCommentsSection` to `useRecordComments` (post, edit, and delete for one's own comments).
 * - List the threads pinned to this record on other records' drawings (`recordCommentsApi.anchored`), with their first
 *   comment, state and a link that opens the drawing at that thread (`?pin=`).
 *
 * Design decisions:
 * - Nothing here knows a module: the link to a drawing comes from the module registry's `getArtefactPath`, and the
 *   pinned list is empty for a type that is never an anchor.
 * - Replying to or resolving a pinned thread is done on its drawing, so this list is read-only.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { recordCommentsApi, type AnchoredThread, type RecordCommentsApi } from "../api/recordComments";
import { useStrings } from "../context/TerminologyContext";
import { useRecordComments } from "../hooks/useRecordComments";
import { getArtefactPath } from "../modules/artefactPaths";
import { ArtefactCommentsSection } from "./ArtefactCommentsSection";
import { Badge } from "./Badge";
import { DetailCard } from "./DetailCard";

/**
 * @param projectId The project the record is opened from.
 * @param artefactType The record's registered type.
 * @param recordId The record.
 * @param currentUserId The viewer, so only their comments offer Edit.
 * @param client The API to use; defaults to the live one (a story injects its own).
 */
export function RecordCommentsCards({
  projectId, artefactType, recordId, currentUserId, client = recordCommentsApi,
}: {
  projectId: string;
  artefactType: string;
  recordId: string;
  currentUserId?: string;
  client?: RecordCommentsApi;
}) {
  const text = useStrings().canvasComments;
  const comments = useRecordComments(projectId, artefactType, recordId, client);
  const [anchored, setAnchored] = useState<AnchoredThread[]>([]);

  useEffect(() => {
    let active = true;
    client.anchored(projectId, artefactType, recordId).then((threads) => {
      if (active) setAnchored(threads);
    }).catch(() => {
      if (active) setAnchored([]);
    });
    return () => {
      active = false;
    };
  }, [client, projectId, artefactType, recordId]);

  const ordinary = (comments.thread?.comments ?? []).filter((c) => c.pin_id === null);
  return (
    <>
      {comments.error && <p role="alert" style={{ color: "var(--color-danger)" }}>{comments.error}</p>}
      <ArtefactCommentsSection
        comments={ordinary} currentUserId={currentUserId}
        onPost={async (body) => { await comments.add({ body }); }}
        onEdit={async (commentId, body) => { await comments.edit(commentId, body); }}
      />
      {anchored.length > 0 && (
        <DetailCard heading={text.pinnedHeading}>
          {anchored.map((t) => {
            const path = getArtefactPath(t.record_type, projectId, t.record_id);
            return (
              <div key={t.pin.id} className="comment-row stack" style={{ gap: "var(--space-1)" }}>
                <div className="row" style={{ justifyContent: "space-between", gap: "var(--space-2)" }}>
                  <span style={{ fontWeight: 600 }}>
                    {path ? <Link to={`${path}?pin=${t.pin.id}`} aria-label={text.openDiagram(t.record_label)}>{t.record_label}</Link> : t.record_label}
                  </span>
                  <span className="row" style={{ gap: "var(--space-2)" }}>
                    {t.pin.resolved && <Badge tone="muted">{text.resolved}</Badge>}
                    <span className="text-muted" style={{ fontSize: "0.8rem" }}>{text.threadCount(t.pin.comment_count)}</span>
                  </span>
                </div>
                {t.comments.map((c) => (
                  <div key={c.id} style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
                    <strong>{c.author_display_name}</strong>{" "}{c.body}
                  </div>
                ))}
              </div>
            );
          })}
        </DetailCard>
      )}
    </>
  );
}
