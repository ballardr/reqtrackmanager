/**
 * Module: pages/ProjectFilesPage
 *
 * The project's Files page: every file the project holds in one filterable list, with a preview of each picture.
 *
 * Responsibilities:
 * - List the files of a project's requirements, actions and requirement comments and the pictures in its report
 *   image library (`POST /projects/{id}/files/search`), each with the origin it came from.
 * - Narrow the list with the shared filters (`useFileFilters`, `FileFilterFields`) plus the nested-project scope.
 *   Every filter lives in the URL, so the list comes back as it was left after opening a record.
 *
 * Design decisions:
 * - Read/browse only: uploads happen from the record a file is attached to (`FileAttachmentList`) or from the report
 *   image library in the layout designer, not here.
 * - A response that arrives after a newer search has been sent is dropped, so typing quickly cannot show stale rows.
 */
import { useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import type { ProjectFile, ProjectFileUploader } from "../api/types";
import { FileFilterFields } from "../components/FileFilterFields";
import { FilesTable } from "../components/FilesTable";
import { FilterPanel } from "../components/FilterPanel";
import { ListPageLayout } from "../components/ListPageLayout";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { ProjectScopeFilter } from "../components/ProjectScopeFilter";
import { Spinner } from "../components/Spinner";
import { useStrings } from "../context/TerminologyContext";
import { useFileFilters } from "../hooks/useFileFilters";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useRestoredRowCount } from "../hooks/useListPosition";
import { useProjectScope } from "../hooks/useProjectScope";
import { useResetOnChange } from "../hooks/useResetOnChange";

const PAGE_SIZE = 50;

/** The Files page of the project in the route (`/projects/:projectId/files`). */
export function ProjectFilesPage() {
  const strings = useStrings();
  const { projectId } = useParams<{ projectId: string }>();
  const [files, setFiles] = useState<ProjectFile[] | null>(null);
  const [total, setTotal] = useState(0);
  const [uploaders, setUploaders] = useState<ProjectFileUploader[]>([]);
  const projectScope = useProjectScope(projectId);
  const filters = useFileFilters();
  const limitFor = useRestoredRowCount(PAGE_SIZE);
  const latestRequest = useRef(0);
  const scopeQuery = projectScope.widened ? `&${projectScope.query}` : "";

  async function loadFiles(offset: number, append: boolean) {
    if (!projectId) return;
    const request = ++latestRequest.current;
    const page = await api.postPage<ProjectFile>(
      `/api/v1/projects/${projectId}/files/search?limit=${limitFor(offset)}&offset=${offset}${scopeQuery}`,
      filters.body(),
    );
    if (request !== latestRequest.current) return;
    setFiles((prev) => (append && prev ? [...prev, ...page.items] : page.items));
    setTotal(page.total);
  }

  const filterKey = [projectId, projectScope.scope, ...filters.key];
  useResetOnChange(filterKey, () => setFiles(null));
  useLoadOnChange(() => loadFiles(0, false), filterKey);
  useLoadOnChange(async () => {
    if (!projectId) return;
    setUploaders(await api.get<ProjectFileUploader[]>(`/api/v1/projects/${projectId}/files/uploaders?${projectScope.query}`));
  }, [projectId, projectScope.scope]);

  return (
    <ListPageLayout
      ready={files !== null}
      loadedRows={files?.length}
      title={strings.files.title}
      filter={
        <FilterPanel
          sectionKey="projectFilesFilters"
          search={filters.search}
          onSearchChange={filters.setSearch}
          searchPlaceholder={strings.files.searchPlaceholder}
          searchAriaLabel={strings.files.searchLabel}
        >
          <FileFilterFields filters={filters} uploaders={uploaders} />
          <ProjectScopeFilter scope={projectScope} />
        </FilterPanel>
      }
    >
      {!files && <Spinner />}
      {files && files.length === 0 && <p className="text-muted">{filters.filtered ? strings.files.emptyFiltered : strings.files.empty}</p>}
      {files && files.length > 0 && <FilesTable files={files} projectId={projectId} />}
      {files && <LoadMoreButton loaded={files.length} total={total} onClick={() => loadFiles(files.length, true)} />}
    </ListPageLayout>
  );
}
