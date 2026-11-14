/**
 * Module: testing/recordCommentsFake
 *
 * An in-memory `RecordCommentsApi` for stories: it keeps one thread and applies each change the way the server does
 * (a new pin opens a thread, the last comment of a thread removes its pin, resolving sets the state), so a story drives the
 * comment layer without a network.
 */
import type {
  AnchoredThread, NewComment, PinChange, PlaceInput, RecordComment, RecordCommentPin, RecordCommentsApi, RecordThread,
} from "../api/recordComments";

/** A comment as the server returns it, with sensible defaults. */
export function buildComment(overrides: Partial<RecordComment> = {}): RecordComment {
  return {
    id: "c-1", pin_id: null, author_id: "user-1", author_display_name: "Alex Reviewer", body: "Looks right.",
    created_at: "2026-11-14T09:00:00Z", edited_at: null, can_edit: true, can_delete: true, attachments: [], ...overrides,
  };
}

/** A pin as the server returns it, with sensible defaults. */
export function buildPin(overrides: Partial<RecordCommentPin> = {}): RecordCommentPin {
  return {
    id: "p-1", anchor_kind: "none", anchor_key: null, x: 120, y: 80, comment_count: 1, resolved: false, resolved_at: null,
    resolved_by_display_name: null, can_move: true, can_delete: true, ...overrides,
  };
}

/**
 * @param initial The thread to start from.
 * @param anchored What `anchored` returns.
 * @returns A `RecordCommentsApi` over that thread, plus `state()` to read it back.
 */
export function fakeRecordComments(
  initial: Partial<RecordThread> = {}, anchored: AnchoredThread[] = [],
): RecordCommentsApi & { state: () => RecordThread } {
  let thread: RecordThread = { comments: [], pins: [], can_pin: true, can_manage: true, ...initial };
  let counter = 100;
  const withCounts = (): RecordThread => ({
    ...thread,
    pins: thread.pins.map((p) => ({ ...p, comment_count: thread.comments.filter((c) => c.pin_id === p.id).length })),
  });
  const place = (p: PlaceInput) => ({ anchor_kind: p.anchor_kind, anchor_key: p.anchor_key ?? null, x: p.x, y: p.y });
  return {
    state: () => withCounts(),
    get: async () => withCounts(),
    add: async (_p, _t, _i, comment: NewComment) => {
      let pinId = comment.pin_id ?? null;
      if (comment.pin) {
        pinId = `p-${++counter}`;
        thread = { ...thread, pins: [...thread.pins, buildPin({ id: pinId, ...place(comment.pin) })] };
      }
      thread = { ...thread, comments: [...thread.comments, buildComment({ id: `c-${++counter}`, pin_id: pinId, body: comment.body })] };
      return withCounts();
    },
    edit: async (_p, _t, _i, commentId, body) => {
      thread = { ...thread, comments: thread.comments.map((c) => (c.id === commentId ? { ...c, body, edited_at: "2026-11-14T10:00:00Z" } : c)) };
      return withCounts();
    },
    remove: async (_p, _t, _i, commentId) => {
      const gone = thread.comments.find((c) => c.id === commentId);
      const comments = thread.comments.filter((c) => c.id !== commentId);
      const emptied = gone?.pin_id && !comments.some((c) => c.pin_id === gone.pin_id);
      thread = { ...thread, comments, pins: emptied ? thread.pins.filter((p) => p.id !== gone.pin_id) : thread.pins };
      return withCounts();
    },
    pin: async (_p, _t, _i, commentId, p) => {
      const id = `p-${++counter}`;
      thread = {
        ...thread, pins: [...thread.pins, buildPin({ id, ...place(p) })],
        comments: thread.comments.map((c) => (c.id === commentId ? { ...c, pin_id: id } : c)),
      };
      return withCounts();
    },
    updatePin: async (_p, _t, _i, pinId, change: PinChange) => {
      thread = {
        ...thread,
        pins: thread.pins.map((pin) => {
          if (pin.id !== pinId) return pin;
          const moved = change.place ? place(change.place) : {};
          const resolved = change.resolved === undefined ? {} : {
            resolved: change.resolved, resolved_at: change.resolved ? "2026-11-14T10:00:00Z" : null,
            resolved_by_display_name: change.resolved ? "Alex Reviewer" : null,
          };
          return { ...pin, ...moved, ...resolved };
        }),
      };
      return withCounts();
    },
    removePin: async (_p, _t, _i, pinId) => {
      thread = { ...thread, pins: thread.pins.filter((p) => p.id !== pinId), comments: thread.comments.filter((c) => c.pin_id !== pinId) };
      return withCounts();
    },
    anchored: async () => anchored,
  };
}
