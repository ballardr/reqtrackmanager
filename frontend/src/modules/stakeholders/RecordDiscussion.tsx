/**
 * Module: modules/stakeholders/RecordDiscussion
 *
 * The Attachments and Comments blocks at the foot of a record's detail page,
 * shared by every record kind in this module: it loads the record's comments
 * and directly attached files itself, and wires `FileAttachmentList` and
 * `ArtefactCommentsSection` to the record's API. A load failure is a toast;
 * the page above keeps working.
 *
 * When `attachmentsReadOnly` (an org record opened inside a project, whose
 * attachments are managed from the org view) the upload/remove controls are
 * disabled with `attachmentsHint` explaining why; comments stay open to every
 * member.
 */
import { useEffect, useState } from "react";

import type { FileAsset } from "../../api/types";
import { ArtefactCommentsSection } from "../../components/ArtefactCommentsSection";
import { FileAttachmentList } from "../../components/FileAttachmentList";
import { toErrorMessage, useToast } from "../../context/ToastContext";

/** A comment as `ArtefactCommentsSection` needs it. */
interface DiscussionComment {
  id: string;
  author_id: string;
  author_display_name: string;
  body: string;
  created_at: string;
  edited_at: string | null;
  attachments: FileAsset[];
}

/** The slice of a record API the discussion blocks call. */
export interface DiscussionApi<C extends DiscussionComment> {
  listComments(id: string, recordId: string): Promise<C[]>;
  addComment(id: string, recordId: string, body: string): Promise<C>;
  editComment(id: string, recordId: string, commentId: string, body: string): Promise<C>;
  uploadCommentAttachment(id: string, recordId: string, commentId: string, file: File): Promise<FileAsset>;
  removeCommentAttachment(id: string, recordId: string, commentId: string, fileId: string): Promise<void>;
  listFiles(id: string, recordId: string): Promise<FileAsset[]>;
  uploadFile(id: string, recordId: string, file: File): Promise<FileAsset>;
  unlinkFile(id: string, recordId: string, fileId: string): Promise<void>;
}

export function RecordDiscussion<C extends DiscussionComment>({
  api, scopeId, recordId, noun, currentUserId, attachmentsReadOnly, attachmentsHint,
}: {
  api: DiscussionApi<C>;
  /** The `organization_id` or `project_id` the API calls are scoped by. */
  scopeId: string;
  recordId: string;
  /** Singular noun for the load-failure toast, e.g. "Persona". */
  noun: string;
  currentUserId: string | undefined;
  attachmentsReadOnly: boolean;
  attachmentsHint?: string;
}) {
  const { showToast } = useToast();
  const [comments, setComments] = useState<C[] | null>(null);
  const [files, setFiles] = useState<FileAsset[]>([]);

  useEffect(() => {
    let active = true;
    Promise.all([api.listComments(scopeId, recordId), api.listFiles(scopeId, recordId)])
      .then(([c, f]) => {
        if (!active) return;
        setComments(c);
        setFiles(f);
      })
      .catch((err) => showToast(toErrorMessage(err, `Could not load this ${noun}'s comments/files.`), "error"));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeId, recordId]);

  return (
    <>
      <div className="stack" style={{ borderTop: "1px solid var(--color-border)", paddingTop: "0.75rem" }}>
        <h3 style={{ margin: 0, fontSize: "0.95rem" }}>Attachments</h3>
        <FileAttachmentList
          files={files}
          disabled={attachmentsReadOnly}
          emptyHint={attachmentsReadOnly ? attachmentsHint : undefined}
          onUpload={async (file) => {
            const asset = await api.uploadFile(scopeId, recordId, file);
            setFiles((prev) => [...prev, asset]);
          }}
          onRemove={async (fileId) => {
            await api.unlinkFile(scopeId, recordId, fileId);
            setFiles((prev) => prev.filter((f) => f.id !== fileId));
          }}
        />
      </div>

      <div className="stack" style={{ borderTop: "1px solid var(--color-border)", paddingTop: "0.75rem" }}>
        <ArtefactCommentsSection
          comments={comments ?? []}
          currentUserId={currentUserId}
          onPost={async (body) => {
            const comment = await api.addComment(scopeId, recordId, body);
            setComments((prev) => [...(prev ?? []), comment]);
            return comment;
          }}
          onEdit={async (commentId, body) => {
            const updated = await api.editComment(scopeId, recordId, commentId, body);
            setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? updated : c)));
          }}
          onUploadAttachment={async (commentId, file) => {
            const asset = await api.uploadCommentAttachment(scopeId, recordId, commentId, file);
            setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? { ...c, attachments: [...c.attachments, asset] } : c)));
          }}
          onRemoveAttachment={async (commentId, fileId) => {
            await api.removeCommentAttachment(scopeId, recordId, commentId, fileId);
            setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? { ...c, attachments: c.attachments.filter((a) => a.id !== fileId) } : c)));
          }}
        />
      </div>
    </>
  );
}
