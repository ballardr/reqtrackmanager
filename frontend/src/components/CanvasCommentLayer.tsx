/**
 * Module: components/CanvasCommentLayer
 *
 * Comments on a graph canvas, as the props a `GraphCanvas` needs: a comment mode, a marker for each pinned thread and a
 * pop-over with its thread. A module passes its record and how its anchors map to canvas ids, and spreads `canvasProps`
 * onto the canvas; it needs no comment code of its own (Modules 16 and 17 reuse it).
 *
 * Responsibilities:
 * - Load the record's comments (`useRecordComments`) and turn the pinned threads into canvas pins, hiding resolved ones or
 *   all of them on request.
 * - In comment mode turn a canvas click into a composer at that spot (anchored to the box or line clicked, else free) and a
 *   dropped pin into a move; open a thread from its marker; centre the canvas on a thread (`focusPin`).
 * - Keep comments out of the layout: they are saved at once, so they never mark a drawing as having unsaved changes.
 *
 * Design decisions:
 * - The canvas stays generic (pins, a render slot, a click callback); everything about comments lives here, and everything
 *   about a record's anchors is a pair of callbacks from the module (`anchorOf`, `placeOf`).
 * - A click that closes an open pop-over only closes it: it does not also start a new comment.
 * - A pin dropped by a drag keeps its new place at once while the change is stored, so it does not jump back.
 * - Comments are not live: the thread is read again when the window regains focus and after each change.
 *
 * Dependencies: `api/recordComments`, `hooks/useRecordComments`, `GraphCanvas` types, `CommentMarker`, `CommentThreadView`.
 */
import { useCallback, useMemo, useRef, useState } from "react";

import type { PinAnchorKind, PlaceInput, RecordComment, RecordCommentPin, RecordCommentsApi } from "../api/recordComments";
import { useStrings } from "../context/TerminologyContext";
import { useRecordComments, type RecordCommentsState } from "../hooks/useRecordComments";
import { CommentComposer } from "./CommentComposer";
import { CommentMarker } from "./CommentMarker";
import { CommentThreadView } from "./CommentThreadView";
import type { GraphCanvasPin, GraphCanvasProps, GraphPinContext, GraphPointAnchor } from "./GraphCanvas";

/** The id of the pin standing for a comment being written. */
const PENDING_PIN_ID = "pending-comment";

/** A click closing a pop-over is not a click placing a comment when it lands within this many milliseconds. */
const CLOSE_CLICK_GRACE_MS = 300;

export interface CanvasCommentsOptions {
  projectId: string;
  artefactType: string;
  recordId: string;
  /** The canvas node or line a stored anchor stands for, or `undefined` for a free pin or an anchor not drawn. */
  anchorOf: (place: { anchor_kind: PinAnchorKind; anchor_key: string | null }) => { kind: "node" | "edge"; id: string } | undefined;
  /** The place a click or a drop becomes: the position and the record key of the box or line it landed on. */
  placeOf: (position: { x: number; y: number }, anchor: GraphPointAnchor) => PlaceInput;
  /** The API to use; defaults to the live one (a story injects its own). */
  client?: RecordCommentsApi;
  /** A thread to open as soon as the comments load (from a link to it). */
  initialPin?: string | null;
}

/** What `useCanvasComments` returns. */
export interface CanvasComments {
  comments: RecordCommentsState;
  /** Whether comment mode is on (a click places a comment instead of selecting). */
  commentMode: boolean;
  setCommentMode: (on: boolean) => void;
  showComments: boolean;
  setShowComments: (on: boolean) => void;
  showResolved: boolean;
  setShowResolved: (on: boolean) => void;
  /** Opens a thread from the Comments list: selects it, shows it and centres the canvas on it. */
  focusPin: (pinId: string) => void;
  /** Starts a comment at a place without a click (the Selection card's "Comment on this box"). */
  startAt: (place: PlaceInput) => void;
  /** Turns comment mode on so the next click on the canvas places an existing ordinary comment (the Comments list's "Pin to diagram"). */
  startPinning: (commentId: string) => void;
  /** The ordinary comment waiting for a click to be placed, or null. */
  pinning: string | null;
  /** The props to spread onto the `GraphCanvas`. */
  canvasProps: Pick<GraphCanvasProps, "mode" | "onCanvasPoint" | "pins" | "renderPin" | "onPinMove" | "centerOn">;
}

/**
 * @param options The record, its anchor mapping and optionally a thread to open.
 * @returns The comment state, its switches and the props for the canvas.
 */
export function useCanvasComments(options: CanvasCommentsOptions): CanvasComments {
  const { projectId, artefactType, recordId, anchorOf, placeOf, client, initialPin = null } = options;
  const text = useStrings().canvasComments;
  const comments = useRecordComments(projectId, artefactType, recordId, client);
  const [commentMode, setCommentMode] = useState(false);
  const [showComments, setShowComments] = useState(true);
  const [showResolved, setShowResolved] = useState(true);
  const [selectedPin, setSelectedPin] = useState<string | null>(initialPin);
  const [pending, setPending] = useState<PlaceInput | null>(null);
  const [pinning, setPinning] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<Record<string, Pick<GraphCanvasPin, "x" | "y" | "anchor">>>({});
  const [centerOn, setCenterOn] = useState<{ x: number; y: number; key: number } | undefined>(undefined);
  const closedAt = useRef(0);

  const thread = comments.thread;
  const byPin = useMemo(() => {
    const found = new Map<string, RecordComment[]>();
    for (const c of thread?.comments ?? []) if (c.pin_id) found.set(c.pin_id, [...(found.get(c.pin_id) ?? []), c]);
    return found;
  }, [thread]);

  /**
   * The canvas anchor of a stored place: the module's node or line, or an anchor naming nothing on the canvas when the
   * place is anchored to a box or line that is not drawn (so the canvas marks the pin as detached and keeps its last place).
   */
  const canvasAnchor = useCallback(
    (place: { anchor_kind: PinAnchorKind; anchor_key: string | null }): GraphCanvasPin["anchor"] => {
      if (place.anchor_kind === "none") return undefined;
      return anchorOf(place) ?? { kind: place.anchor_kind, id: "" };
    },
    [anchorOf],
  );

  const closeAll = useCallback(() => {
    closedAt.current = Date.now();
    setSelectedPin(null);
    setPending(null);
  }, []);

  const pins = useMemo<GraphCanvasPin[]>(() => {
    const shown: GraphCanvasPin[] = [];
    if (showComments) {
      for (const pin of thread?.pins ?? []) {
        if (pin.resolved && !showResolved && pin.id !== selectedPin) continue;
        shown.push({ id: pin.id, movable: pin.can_move, anchor: canvasAnchor(pin), ...(overrides[pin.id] ?? { x: pin.x, y: pin.y }) });
      }
    }
    if (pending) shown.push({ id: PENDING_PIN_ID, x: pending.x, y: pending.y, anchor: canvasAnchor({ anchor_kind: pending.anchor_kind, anchor_key: pending.anchor_key ?? null }) });
    return shown;
  }, [thread, showComments, showResolved, selectedPin, pending, overrides, canvasAnchor]);

  const renderPin = useCallback(
    (pin: GraphCanvasPin, context: GraphPinContext) => {
      if (pin.id === PENDING_PIN_ID) {
        return (
          <CommentMarker
            author="" count={0} resolved={false} detached={false} isNew open title={text.composerTitle} onToggle={closeAll} onClose={closeAll}
          >
            <CommentComposer
              error={comments.error}
              onCancel={closeAll}
              onPost={async (body) => {
                if (!pending) return false;
                const stored = await comments.add({ body, pin: pending });
                if (stored) setPending(null);
                return stored;
              }}
            />
          </CommentMarker>
        );
      }
      const record: RecordCommentPin | undefined = thread?.pins.find((p) => p.id === pin.id);
      const list = byPin.get(pin.id) ?? [];
      if (!record) return null;
      return (
        <CommentMarker
          author={list[0]?.author_display_name ?? ""} count={record.comment_count} resolved={record.resolved} detached={context.detached}
          open={selectedPin === pin.id} title={text.threadTitle}
          onToggle={() => setSelectedPin(selectedPin === pin.id ? null : pin.id)} onClose={closeAll}
        >
          <CommentThreadView
            pin={record} comments={list} error={comments.error}
            onReply={(body) => comments.add({ body, pin_id: pin.id })}
            onEdit={comments.edit}
            onRemove={comments.remove}
            onResolve={(resolved) => comments.updatePin(pin.id, { resolved })}
            onRemoveThread={async () => {
              const stored = await comments.removePin(pin.id);
              if (stored) setSelectedPin(null);
              return stored;
            }}
          />
        </CommentMarker>
      );
    },
    [text, comments, pending, thread, byPin, selectedPin, closeAll],
  );

  const onCanvasPoint = useCallback(
    (position: { x: number; y: number }, anchor: GraphPointAnchor) => {
      // The press that closed a pop-over is the same click; it must not also open a composer.
      if (Date.now() - closedAt.current < CLOSE_CLICK_GRACE_MS) return;
      if (pinning !== null) {
        const commentId = pinning;
        setPinning(null);
        void comments.pin(commentId, placeOf(position, anchor));
        return;
      }
      if (selectedPin !== null || pending !== null) {
        closeAll();
        return;
      }
      setPending(placeOf(position, anchor));
    },
    [pinning, selectedPin, pending, comments, closeAll, placeOf],
  );

  const onPinMove = useCallback(
    (pinId: string, position: { x: number; y: number }, anchor: GraphPointAnchor) => {
      if (pinId === PENDING_PIN_ID) return;
      const place = placeOf(position, anchor);
      setOverrides((o) => ({ ...o, [pinId]: { x: place.x, y: place.y, anchor: canvasAnchor({ anchor_kind: place.anchor_kind, anchor_key: place.anchor_key ?? null }) } }));
      void comments.updatePin(pinId, { place }).finally(() =>
        setOverrides((o) => {
          return Object.fromEntries(Object.entries(o).filter(([id]) => id !== pinId));
        }),
      );
    },
    [comments, placeOf, canvasAnchor],
  );

  const focusPin = useCallback(
    (pinId: string) => {
      const pin = thread?.pins.find((p) => p.id === pinId);
      if (!pin) return;
      setShowComments(true);
      setShowResolved(true);
      setSelectedPin(pinId);
      setCenterOn((c) => ({ x: pin.x, y: pin.y, key: (c?.key ?? 0) + 1 }));
    },
    [thread],
  );

  return {
    comments, commentMode, setCommentMode: (on) => { setCommentMode(on); if (!on) setPinning(null); }, showComments, setShowComments, showResolved, setShowResolved, focusPin,
    startAt: (place) => {
      setSelectedPin(null);
      setPending(place);
    },
    pinning,
    startPinning: (commentId) => {
      setPinning(commentId);
      setCommentMode(true);
    },
    canvasProps: { mode: commentMode ? "comment" : "select", onCanvasPoint: commentMode ? onCanvasPoint : undefined, pins, renderPin, onPinMove, centerOn },
  };
}
