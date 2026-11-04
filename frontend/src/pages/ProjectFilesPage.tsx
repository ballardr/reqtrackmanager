/**
 * Module: pages/ProjectFilesPage
 *
 * The project's Files page: every file the project holds in one filterable list, with a preview of each picture.
 *
 * Responsibilities:
 * - List the files of a project's requirements, actions and requirement comments and the pictures in its report
 *   image library (`POST /projects/{id}/files/search`), each with the origin it came from.
 * - Narrow the list with a side filter panel: file name, source, file type, uploader and an upload window, plus the
 *   nested-project scope. Every filter lives in the URL, so the list comes back as it was left after opening a record.
 *
 * Design decisions:
 * - Read/browse only: uploads happen from the record a file is attached to (`FileAttachmentList`) or from the report
 *   image library in the layout designer, not here.
 * - The file name typed in the search is sent in a POST body, never in an API URL the server logs.
 * - The upload window is picked as the person's local days and sent as the two UTC instants they bound
 *   (`localDayWindow`), because an upload time is stored in UTC and only the browser knows the person's timezone.
 * - A response that arrives after a newer search has been sent is dropped, so typing quickly cannot show stale rows.
 */
import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, fileUrl } from "../api/client";
import { rowProjectId } from "../api/projectScope";
import {
  PROJECT_FILE_SOURCES,
  type ProjectFile,
  type ProjectFileKind,
  type ProjectFileSource,
  type ProjectFileUploader,
} from "../api/types";
import { FileDetailsToggle } from "../components/FileDetailsPanel";
import { FileThumbnail } from "../components/FileThumbnail";
import { FilterField, FilterPanel } from "../components/FilterPanel";
import { DateField } from "../components/FormFields";
import { ListPageLayout } from "../components/ListPageLayout";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { ProjectScopeFilter } from "../components/ProjectScopeFilter";
import { ProjectScopeLabel } from "../components/ProjectScopeLabel";
import { Spinner } from "../components/Spinner";
import { useStrings } from "../context/TerminologyContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useRestoredRowCount } from "../hooks/useListPosition";
import { useProjectScope } from "../hooks/useProjectScope";
import { useResetOnChange } from "../hooks/useResetOnChange";
import { useUrlChoice, useUrlText } from "../hooks/useUrlFilter";
import { formatFileSize } from "../utils/formatFileSize";
import { localDayWindow } from "../utils/localDate";

const PAGE_SIZE = 50;
const KINDS: readonly ProjectFileKind[] = ["image", "document", "other"];

/** The Files page of the project in the route (`/projects/:projectId/files`). */
export function ProjectFilesPage() {
  const strings = useStrings();
  const { projectId } = useParams<{ projectId: string }>();
  const [files, setFiles] = useState<ProjectFile[] | null>(null);
  const [total, setTotal] = useState(0);
  const [uploaders, setUploaders] = useState<ProjectFileUploader[]>([]);
  const projectScope = useProjectScope(projectId);
  const [search, setSearch] = useUrlText("q");
  const [source, setSource] = useUrlChoice<ProjectFileSource>("source", PROJECT_FILE_SOURCES);
  const [kind, setKind] = useUrlChoice<ProjectFileKind>("type", KINDS);
  const [uploader, setUploader] = useUrlText("by");
  const [from, setFrom] = useUrlText("from");
  const [to, setTo] = useUrlText("to");
  const limitFor = useRestoredRowCount(PAGE_SIZE);
  const latestRequest = useRef(0);
  const scopeQuery = projectScope.widened ? `&${projectScope.query}` : "";

  async function loadFiles(offset: number, append: boolean) {
    if (!projectId) return;
    const request = ++latestRequest.current;
    const range = localDayWindow(from, to);
    const page = await api.postPage<ProjectFile>(
      `/api/v1/projects/${projectId}/files/search?limit=${limitFor(offset)}&offset=${offset}${scopeQuery}`,
      {
        search,
        sources: source ? [source] : [],
        kind: kind || null,
        uploaded_by: uploader || null,
        uploaded_from: range.from ?? null,
        uploaded_before: range.before ?? null,
      },
    );
    if (request !== latestRequest.current) return;
    setFiles((prev) => (append && prev ? [...prev, ...page.items] : page.items));
    setTotal(page.total);
  }

  const filterKey = [projectId, projectScope.scope, search, source, kind, uploader, from, to];
  useResetOnChange(filterKey, () => setFiles(null));
  useLoadOnChange(() => loadFiles(0, false), filterKey);
  useLoadOnChange(async () => {
    if (!projectId) return;
    setUploaders(await api.get<ProjectFileUploader[]>(`/api/v1/projects/${projectId}/files/uploaders?${projectScope.query}`));
  }, [projectId, projectScope.scope]);

  function originLink(f: ProjectFile): { to: string; label: string } | null {
    if (f.source === "report_image") {
      return { to: `/projects/${rowProjectId(f, projectId ?? "")}/admin/reportSetup`, label: strings.files.reportImageOrigin };
    }
    if (f.source === "action_attachment" && f.action_id) {
      return {
        to: `/projects/${rowProjectId(f, projectId ?? "")}/actions/${f.action_id}`,
        label: f.action_unique_code ? `${f.action_unique_code} — ${f.action_title}` : (f.action_title ?? f.action_id),
      };
    }
    if (f.requirement_id) {
      return {
        to: `/projects/${rowProjectId(f, projectId ?? "")}/requirements/${f.requirement_id}`,
        label: f.requirement_unique_code
          ? `${f.requirement_unique_code} — ${f.requirement_name}`
          : (f.requirement_name ?? f.requirement_id),
      };
    }
    return null;
  }

  const filtered = Boolean(search || source || kind || uploader || from || to);

  return (
    <ListPageLayout
      ready={files !== null}
      loadedRows={files?.length}
      title={strings.files.title}
      filter={
        <FilterPanel
          sectionKey="projectFilesFilters"
          search={search}
          onSearchChange={setSearch}
          searchPlaceholder={strings.files.searchPlaceholder}
          searchAriaLabel={strings.files.searchLabel}
        >
          <FilterField label={strings.files.filterSource}>
            <select className="input" value={source} onChange={(e) => setSource(e.target.value as ProjectFileSource | "")}>
              <option value="">{strings.files.allSources}</option>
              {PROJECT_FILE_SOURCES.map((s) => (
                <option key={s} value={s}>{strings.files.sources[s]}</option>
              ))}
            </select>
          </FilterField>
          <FilterField label={strings.files.filterKind}>
            <select className="input" value={kind} onChange={(e) => setKind(e.target.value as ProjectFileKind | "")}>
              <option value="">{strings.files.allKinds}</option>
              {KINDS.map((k) => (
                <option key={k} value={k}>{strings.files.kinds[k]}</option>
              ))}
            </select>
          </FilterField>
          <FilterField label={strings.files.filterUploader}>
            <select className="input" value={uploader} onChange={(e) => setUploader(e.target.value)}>
              <option value="">{strings.files.allUploaders}</option>
              {uploaders.map((u) => (
                <option key={u.id} value={u.id}>{u.display_name}</option>
              ))}
            </select>
          </FilterField>
          <DateField helpNotNeeded label={strings.files.uploadedFrom} value={from} onChange={setFrom} inputProps={{ max: to || undefined }} />
          <DateField helpNotNeeded label={strings.files.uploadedTo} value={to} onChange={setTo} inputProps={{ min: from || undefined }} />
          <ProjectScopeFilter scope={projectScope} />
        </FilterPanel>
      }
    >
      {!files && <Spinner />}
      {files && files.length === 0 && <p className="text-muted">{filtered ? strings.files.emptyFiltered : strings.files.empty}</p>}
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
                      <span className="row" style={{ gap: "var(--space-2)", flexWrap: "nowrap" }}>
                        <FileThumbnail file={f.file} />
                        <a href={fileUrl(f.file.id)} target="_blank" rel="noreferrer" style={{ overflowWrap: "anywhere" }}>
                          {f.file.filename}
                        </a>
                        <FileDetailsToggle file={f.file} />
                      </span>
                    </td>
                    <td>
                      <div className="stack" style={{ gap: "0.1rem" }}>
                        <span className="text-muted" style={{ fontSize: "0.8rem" }}>
                          {strings.files.sources[f.source]}
                        </span>
                        {link && <Link to={link.to}>{link.label}</Link>}
                        <ProjectScopeLabel row={f} />
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
    </ListPageLayout>
  );
}
