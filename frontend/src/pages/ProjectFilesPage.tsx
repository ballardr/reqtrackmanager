import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, fileUrl } from "../api/client";
import type { ProjectFile } from "../api/types";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { Spinner } from "../components/Spinner";
import { useStrings } from "../context/TerminologyContext";

const PAGE_SIZE = 50;

/** Human-readable file size (e.g. "12.4 KB") — no existing shared helper for
 * this (`size_bytes` was never actually rendered anywhere before this page:
 * `FileAttachmentList.tsx`'s per-requirement/action lists only ever show a
 * filename link). Kept local rather than promoted to a shared util until a
 * second call site needs it. */
function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(1)} ${units[unitIndex]}`;
}

/**
 * Project-wide file browser (`GET /projects/{id}/files`) — fills the gap
 * behind `ProjectOverviewPage`'s "Files" metric tile: before this page
 * existed, `FileAsset` had no `project_id` of its own, so the only way to
 * see a project's files was to open each requirement/action/comment one at
 * a time and check its own attachments card. This page is read/browse only
 * — uploads still happen from the requirement/action/comment they're
 * attached to (`FileAttachmentList.tsx`), not from here.
 *
 * Reuses `FileAttachmentList.tsx`'s own "download link via `fileUrl(id)`"
 * approach for each row, since that's the same `GET /files/{id}` endpoint
 * every other download link in the app already uses. A flat list needs one
 * thing that page's per-entity list doesn't: an "Origin" column linking
 * back to whichever requirement/action the file came from, since a bare
 * filename list gives no way to tell where each file came from.
 */
export function ProjectFilesPage() {
  const strings = useStrings();
  const { projectId } = useParams<{ projectId: string }>();
  const [files, setFiles] = useState<ProjectFile[] | null>(null);
  const [total, setTotal] = useState(0);

  async function loadFiles(offset: number, append: boolean) {
    if (!projectId) return;
    const page = await api.getPage<ProjectFile>(
      `/api/v1/projects/${projectId}/files?limit=${PAGE_SIZE}&offset=${offset}`
    );
    setFiles((prev) => (append && prev ? [...prev, ...page.items] : page.items));
    setTotal(page.total);
  }

  useEffect(() => {
    setFiles(null);
    loadFiles(0, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  function originLink(f: ProjectFile): { to: string; label: string } | null {
    if (f.source === "action_attachment" && f.action_id) {
      return {
        to: `/projects/${projectId}/actions/${f.action_id}`,
        label: f.action_unique_code ? `${f.action_unique_code} — ${f.action_title}` : (f.action_title ?? f.action_id),
      };
    }
    if (f.requirement_id) {
      return {
        to: `/projects/${projectId}/requirements/${f.requirement_id}`,
        label: f.requirement_unique_code
          ? `${f.requirement_unique_code} — ${f.requirement_name}`
          : (f.requirement_name ?? f.requirement_id),
      };
    }
    return null;
  }

  function sourceLabel(source: ProjectFile["source"]): string {
    if (source === "action_attachment") return strings.files.sourceActionAttachment;
    if (source === "comment_attachment") return strings.files.sourceCommentAttachment;
    return strings.files.sourceRequirementAttachment;
  }

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>{strings.files.title}</h1>

      {!files && <Spinner />}
      {files && files.length === 0 && <p className="text-muted">{strings.files.empty}</p>}
      {files && files.length > 0 && (
        <div className="card" style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>{strings.files.columnFilename}</th>
                <th>{strings.files.columnOrigin}</th>
                <th>{strings.files.columnUploadedBy}</th>
                <th>{strings.files.columnUploadedAt}</th>
                <th>{strings.files.columnSize}</th>
              </tr>
            </thead>
            <tbody>
              {files.map((f) => {
                const link = originLink(f);
                return (
                  <tr key={`${f.source}-${f.file.id}-${f.requirement_id ?? ""}-${f.action_id ?? ""}-${f.comment_id ?? ""}`}>
                    <td>
                      <a href={fileUrl(f.file.id)} target="_blank" rel="noreferrer">
                        {f.file.filename}
                      </a>
                    </td>
                    <td>
                      <div className="stack" style={{ gap: "0.1rem" }}>
                        <span className="text-muted" style={{ fontSize: "0.8rem" }}>
                          {sourceLabel(f.source)}
                        </span>
                        {link && <Link to={link.to}>{link.label}</Link>}
                      </div>
                    </td>
                    <td className="text-muted">{f.uploaded_by_display_name}</td>
                    <td className="text-muted">{new Date(f.file.created_at).toLocaleString()}</td>
                    <td className="text-muted">{formatFileSize(f.file.size_bytes)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {files && <LoadMoreButton loaded={files.length} total={total} onClick={() => loadFiles(files.length, true)} />}
    </div>
  );
}
