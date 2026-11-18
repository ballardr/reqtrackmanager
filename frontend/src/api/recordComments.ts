/**
 * Module: api/recordComments
 *
 * Types and calls for the generic record comments: ordinary comments on a record and pinned threads on its drawing
 * (`/projects/{id}/artefacts/{type}/{id}/comments`), for every type a module opted in. Every write returns the record's
 * whole thread, so a caller redraws from one answer.
 *
 * {@link RecordCommentsApi} is injectable so stories stay off the network.
 */
import { api } from "./client";

/** How a pin is attached: a free spot, a box (`node`) or a line (`edge`). */
export type PinAnchorKind = "none" | "node" | "edge";

/** Where a pin sits: a free spot (no key) or a box or line (its record id) and the canvas position. */
export interface PinPlace {
  anchor_kind: PinAnchorKind;
  anchor_key: string | null;
  x: number;
  y: number;
}

/** One comment, with its author's name and what the viewer may do with it. */
export interface RecordComment {
  id: string;
  /** The pinned thread it belongs to, or null for an ordinary comment on the record. */
  pin_id: string | null;
  author_id: string | null;
  author_display_name: string;
  body: string;
  created_at: string;
  edited_at: string | null;
  can_edit: boolean;
  can_delete: boolean;
  /** Always empty: these comments take no files. The server does not send it; `withAttachments` adds it so the shared comment card renders them. */
  attachments: never[];
}

/** One pinned thread: its place, its state and what the viewer may do with it. */
export interface RecordCommentPin extends PinPlace {
  id: string;
  comment_count: number;
  resolved: boolean;
  resolved_at: string | null;
  resolved_by_display_name: string | null;
  can_move: boolean;
  can_delete: boolean;
}

/** Everything a record's comments hold. */
export interface RecordThread {
  comments: RecordComment[];
  pins: RecordCommentPin[];
  /** The record has a drawing a comment can be pinned on. */
  can_pin: boolean;
  /** The viewer may delete others' comments and move their pins. */
  can_manage: boolean;
}

/** A pinned thread on another record's drawing that is anchored to a box or line (read-only). */
export interface AnchoredThread {
  record_type: string;
  record_id: string;
  record_label: string;
  pin: RecordCommentPin;
  comments: RecordComment[];
}

/** A change to a pin: a new place and/or a resolved state. */
export interface PinChange {
  place?: PlaceInput;
  resolved?: boolean;
}

/** A pin's place as a request sends it. */
export interface PlaceInput {
  anchor_kind: PinAnchorKind;
  anchor_key?: string | null;
  x: number;
  y: number;
}

/** What a new comment is: ordinary (neither), a reply (`pin_id`) or the first of a new pin (`pin`). */
export interface NewComment {
  body: string;
  pin_id?: string;
  pin?: PlaceInput;
}

/** The comments of one record; injectable for stories. */
export interface RecordCommentsApi {
  get(projectId: string, type: string, id: string): Promise<RecordThread>;
  add(projectId: string, type: string, id: string, comment: NewComment): Promise<RecordThread>;
  edit(projectId: string, type: string, id: string, commentId: string, body: string): Promise<RecordThread>;
  remove(projectId: string, type: string, id: string, commentId: string): Promise<RecordThread>;
  /** Places an ordinary comment on the record's drawing. */
  pin(projectId: string, type: string, id: string, commentId: string, place: PlaceInput): Promise<RecordThread>;
  /** Moves or re-anchors a pin and/or resolves or reopens its thread. */
  updatePin(projectId: string, type: string, id: string, pinId: string, change: PinChange): Promise<RecordThread>;
  /** Deletes a whole thread. */
  removePin(projectId: string, type: string, id: string, pinId: string): Promise<RecordThread>;
  /** The pinned threads on the project's drawings anchored to this box or line. */
  anchored(projectId: string, type: string, id: string): Promise<AnchoredThread[]>;
}

/** The thread as the shared comment card needs it: each comment with an (always empty) attachments list the server does not send. */
function withAttachments(thread: Omit<RecordThread, "comments"> & { comments: Omit<RecordComment, "attachments">[] }): RecordThread {
  return { ...thread, comments: thread.comments.map((c) => ({ ...c, attachments: [] })) };
}

function base(projectId: string, type: string, id: string): string {
  return `/api/v1/projects/${projectId}/artefacts/${encodeURIComponent(type)}/${id}`;
}

/** The live implementation of {@link RecordCommentsApi}. */
type WireThread = Parameters<typeof withAttachments>[0];

export const recordCommentsApi: RecordCommentsApi = {
  get: async (projectId, type, id) => withAttachments(await api.get<WireThread>(`${base(projectId, type, id)}/comments`)),
  add: async (projectId, type, id, comment) =>
    withAttachments(await api.post<WireThread>(`${base(projectId, type, id)}/comments`, comment)),
  edit: async (projectId, type, id, commentId, body) =>
    withAttachments(await api.patch<WireThread>(`${base(projectId, type, id)}/comments/${commentId}`, { body })),
  remove: async (projectId, type, id, commentId) =>
    withAttachments(await api.delete<WireThread>(`${base(projectId, type, id)}/comments/${commentId}`)),
  pin: async (projectId, type, id, commentId, place) =>
    withAttachments(await api.post<WireThread>(`${base(projectId, type, id)}/comments/${commentId}/pin`, { pin: place })),
  updatePin: async (projectId, type, id, pinId, change) =>
    withAttachments(await api.patch<WireThread>(`${base(projectId, type, id)}/comment-pins/${pinId}`, { pin: change.place, resolved: change.resolved })),
  removePin: async (projectId, type, id, pinId) =>
    withAttachments(await api.delete<WireThread>(`${base(projectId, type, id)}/comment-pins/${pinId}`)),
  anchored: async (projectId, type, id) =>
    (await api.get<{ threads: (Omit<AnchoredThread, "comments"> & { comments: Omit<RecordComment, "attachments">[] })[] }>(`${base(projectId, type, id)}/anchored-comments`))
      .threads.map((t) => ({ ...t, comments: t.comments.map((c) => ({ ...c, attachments: [] })) })),
};
