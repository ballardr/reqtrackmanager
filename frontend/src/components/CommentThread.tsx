import { Heart } from "lucide-react";
import { useState } from "react";

import type { Comment } from "../api/types";
import { t } from "../i18n/strings";

const strings = t();

/**
 * Discussion thread shared by requirement and change-request detail pages
 * (mockup: author name, timestamp, and a heart reaction count per comment).
 */
export function CommentThread({
  comments,
  onPost,
  onToggleReaction,
}: {
  comments: Comment[];
  onPost: (body: string) => Promise<void>;
  onToggleReaction: (commentId: string, reacted: boolean) => Promise<void>;
}) {
  const [newComment, setNewComment] = useState("");

  async function submit() {
    if (!newComment.trim()) return;
    await onPost(newComment);
    setNewComment("");
  }

  return (
    <div className="stack">
      {comments.map((c) => (
        <div key={c.id} className="card stack" style={{ gap: "0.35rem" }}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <span style={{ fontWeight: 600 }}>{c.author_display_name}</span>
            <span className="text-muted" style={{ fontSize: "0.8rem" }}>
              {new Date(c.created_at).toLocaleString()}
            </span>
          </div>
          <div>{c.body}</div>
          <button
            className="btn"
            style={{ alignSelf: "flex-start" }}
            title={strings.requirements.reactionToggle}
            onClick={() => onToggleReaction(c.id, c.reacted_by_me)}
          >
            <Heart size={14} fill={c.reacted_by_me ? "currentColor" : "none"} />
            {c.reaction_count > 0 ? c.reaction_count : ""}
          </button>
        </div>
      ))}
      <div className="row">
        <input
          className="input"
          placeholder={strings.requirements.addComment}
          value={newComment}
          onChange={(e) => setNewComment(e.target.value)}
        />
        <button className="btn" onClick={submit}>
          {strings.requirements.addComment}
        </button>
      </div>
    </div>
  );
}
