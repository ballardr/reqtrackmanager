/**
 * Module: modules/architecture/DiagramCommentsPanel
 *
 * The Comments tab of the diagram editor: every comment on the diagram in one list, the way the record's own page lists
 * comments, with the pinned threads marked.
 *
 * Responsibilities:
 * - List the diagram's comments with the shared `ArtefactCommentsSection` (write, and edit one's own), filtered by a
 *   thread's state (Open, Resolved, All; an ordinary comment is always shown).
 * - Mark a comment that is part of a pinned thread with a "Pinned" chip, what it is anchored to (a box, a connection, the
 *   canvas, or "removed" when the box or line has left the drawing) and its state, with "Show on drawing" (selects and
 *   centres the thread) and, on an ordinary comment, "Pin to diagram"; offer Delete on a comment the server allows.
 *
 * Design decisions:
 * - It is the text alternative of the canvas markers: everything a marker offers is reachable here without a pointer.
 * - It stores nothing: every action is a callback onto the page's comment state.
 */
import { useMemo, useState } from "react";

import type { RecordComment } from "../../api/recordComments";
import { ArtefactCommentsSection } from "../../components/ArtefactCommentsSection";
import { Badge } from "../../components/Badge";
import type { CanvasComments } from "../../components/CanvasCommentLayer";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { LabeledSelect } from "../../components/LabeledSelect";
import { useStrings } from "../../context/TerminologyContext";
import type { PinDescriber } from "./diagramComments";

type StateFilter = "open" | "resolved" | "all";

/**
 * @param layer The page's comment state and actions (`useCanvasComments`).
 * @param describe How the drawing names what a thread is anchored to (a block diagram's boxes and connections, a state machine
 *   diagram's states and transitions), so this list serves both editors.
 * @param currentUserId The viewer, so only their comments offer Edit.
 * @param onShow Called after "Show on drawing" selects the thread, so the page can switch to the Drawing tab.
 */
export function DiagramCommentsPanel({
  layer, describe, currentUserId, onShow,
}: {
  layer: CanvasComments;
  describe: PinDescriber;
  currentUserId?: string;
  onShow: () => void;
}) {
  const text = useStrings().canvasComments;
  const [filter, setFilter] = useState<StateFilter>("all");
  const [deleting, setDeleting] = useState<RecordComment | null>(null);
  const thread = layer.comments.thread;
  const pins = useMemo(() => new Map((thread?.pins ?? []).map((p) => [p.id, p])), [thread]);
  const shown = (thread?.comments ?? []).filter((c) => {
    if (c.pin_id === null || filter === "all") return true;
    const resolved = pins.get(c.pin_id)?.resolved ?? false;
    return filter === "resolved" ? resolved : !resolved;
  });

  /** What a pinned thread is anchored to, in words. */
  function anchorText(pinId: string): string {
    const pin = pins.get(pinId);
    if (!pin) return "";
    if (pin.anchor_kind === "none") return text.pinnedFree;
    if (!describe.drawn(pin)) return text.pinnedGone;
    if (pin.anchor_kind === "node") return text.pinnedOnBox(describe.boxName(pin.anchor_key ?? ""));
    return text.pinnedOnLine(describe.lineName(pin.anchor_key ?? ""));
  }

  return (
    <div className="stack">
      <LabeledSelect
        label={text.filterLabel} helpNotNeeded autoWidth placeholder={null} value={filter}
        onChange={(next) => setFilter(next as StateFilter)}
        options={[
          { value: "all", label: text.filterAll }, { value: "open", label: text.filterOpen }, { value: "resolved", label: text.filterResolved },
        ]}
      />
      {layer.comments.error && <p role="alert" style={{ color: "var(--color-danger)" }}>{layer.comments.error}</p>}
      <ArtefactCommentsSection
        comments={shown} currentUserId={currentUserId}
        onPost={async (body) => { await layer.comments.add({ body }); }}
        onEdit={async (commentId, body) => { await layer.comments.edit(commentId, body); }}
        renderMeta={(c) => {
          const pin = c.pin_id ? pins.get(c.pin_id) : undefined;
          return (
            <div className="row" style={{ gap: "var(--space-2)", flexWrap: "wrap", alignItems: "center" }}>
              {pin && (
                <>
                  <Badge tone="info">{text.pinned}</Badge>
                  <span className="text-muted">{anchorText(pin.id)}</span>
                  {pin.resolved && <Badge tone="muted">{text.resolved}</Badge>}
                  <button type="button" className="btn btn-sm" onClick={() => { layer.focusPin(pin.id); onShow(); }}>{text.showOnDrawing}</button>
                </>
              )}
              {!pin && thread?.can_pin && (
                <button type="button" className="btn btn-sm" onClick={() => { layer.startPinning(c.id); onShow(); }}>{text.pinToDiagram}</button>
              )}
              {c.can_delete && !pin && <button type="button" className="btn btn-sm" onClick={() => setDeleting(c)}>{text.delete}</button>}
            </div>
          );
        }}
      />
      {deleting && (
        <ConfirmDialog
          title={text.delete} message="This comment will be deleted." confirmLabel={text.delete}
          onCancel={() => setDeleting(null)}
          onConfirm={() => { const comment = deleting; setDeleting(null); void layer.comments.remove(comment.id); }}
        />
      )}
    </div>
  );
}
