/**
 * Module: components/FilesTable
 *
 * The table both Files pages draw: a preview and name, the origin the file hangs from (with a link to the record),
 * who uploaded it, when and how large it is.
 *
 * Responsibilities:
 * - Link each row to the record, action or report setup its file came from, inside the row's own project
 *   (`rowProjectId`), so a row of another project of a widened list opens in that project.
 * - On the organisation page (`showProject`) add a Project column linking to the project instead of the
 *   "From <project>" label a widened project list carries.
 *
 * Design decisions:
 * - Read-only: uploads happen from the record a file is attached to or from the report image library.
 */
import { Link } from "react-router-dom";

import { fileUrl } from "../api/client";
import { rowProjectId } from "../api/projectScope";
import type { ProjectFile } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { formatFileSize } from "../utils/formatFileSize";
import { FileDetailsToggle } from "./FileDetailsPanel";
import { FileThumbnail } from "./FileThumbnail";
import { ProjectScopeLabel } from "./ProjectScopeLabel";

/**
 * @param files The rows to draw.
 * @param projectId The project the page shows; a row without `from_project_id` belongs to it.
 * @param showProject Add a Project column (the organisation page, where every row names its project).
 */
export function FilesTable({ files, projectId = "", showProject = false }: { files: ProjectFile[]; projectId?: string; showProject?: boolean }) {
  const strings = useStrings();

  function originLink(f: ProjectFile): { to: string; label: string } | null {
    const project = rowProjectId(f, projectId);
    if (f.source === "report_image") {
      return { to: `/projects/${project}/admin/reportSetup`, label: strings.files.reportImageOrigin };
    }
    if (f.source === "action_attachment" && f.action_id) {
      return {
        to: `/projects/${project}/actions/${f.action_id}`,
        label: f.action_unique_code ? `${f.action_unique_code} — ${f.action_title}` : (f.action_title ?? f.action_id),
      };
    }
    if (f.requirement_id) {
      return {
        to: `/projects/${project}/requirements/${f.requirement_id}`,
        label: f.requirement_unique_code
          ? `${f.requirement_unique_code} — ${f.requirement_name}`
          : (f.requirement_name ?? f.requirement_id),
      };
    }
    return null;
  }

  return (
    <div className="card" style={{ overflowX: "auto" }}>
      <table>
        <thead>
          <tr>
            <th>{strings.files.columnFilename}</th>
            {showProject && <th>{strings.files.columnProject}</th>}
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
              <tr key={`${f.source}-${f.file.id}-${f.requirement_id ?? ""}-${f.action_id ?? ""}-${f.comment_id ?? ""}-${f.from_project_id ?? ""}`}>
                <td>
                  <span className="row" style={{ gap: "var(--space-2)", flexWrap: "nowrap" }}>
                    <FileThumbnail file={f.file} />
                    <a href={fileUrl(f.file.id)} target="_blank" rel="noreferrer" style={{ overflowWrap: "anywhere" }}>
                      {f.file.filename}
                    </a>
                    <FileDetailsToggle file={f.file} />
                  </span>
                </td>
                {showProject && (
                  <td>
                    {f.from_project_id ? <Link to={`/projects/${f.from_project_id}`}>{f.from_project_name}</Link> : null}
                  </td>
                )}
                <td>
                  <div className="stack" style={{ gap: "0.1rem" }}>
                    <span className="text-muted" style={{ fontSize: "0.8rem" }}>
                      {strings.files.sources[f.source]}
                    </span>
                    {link && <Link to={link.to}>{link.label}</Link>}
                    {!showProject && <ProjectScopeLabel row={f} />}
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
  );
}
