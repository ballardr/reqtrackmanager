/**
 * Module: pages/OrgFilesPage
 *
 * The organisation's Files page: the files of every project the person can open, in one filterable list.
 *
 * Responsibilities:
 * - List the files of the person's projects in the organisation (`POST /orgs/{id}/files/search`), each row naming
 *   its project, with the same filters as the project page (`useFileFilters`, `FileFilterFields`) plus a project
 *   filter and a switch for archived projects. Every filter lives in the URL.
 * - Say when the server cut the list at its project limit.
 *
 * Design decisions:
 * - Shows only what the server returns for the person: it covers the projects they hold a role in, never every
 *   project of the organisation, so an administrator without a project role sees no files from that project.
 * - Read/browse only, like the project page; the table is the shared `FilesTable` with a Project column.
 */
import { useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import type { OrganizationFileProject, ProjectFile, ProjectFileUploader } from "../api/types";
import { FileFilterFields } from "../components/FileFilterFields";
import { FilesTable } from "../components/FilesTable";
import { FilterCheckbox, FilterPanel } from "../components/FilterPanel";
import { FilterSelect } from "../components/FilterSelect";
import { ListPageLayout } from "../components/ListPageLayout";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { Spinner } from "../components/Spinner";
import { useOrgLabelCapitalized } from "../context/BrandingContext";
import { useStrings } from "../context/TerminologyContext";
import { useFileFilters } from "../hooks/useFileFilters";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useRestoredRowCount } from "../hooks/useListPosition";
import { useResetOnChange } from "../hooks/useResetOnChange";
import { useUrlFlag, useUrlText } from "../hooks/useUrlFilter";

const PAGE_SIZE = 50;

/** The Files page of the organisation in the route (`/orgs/:orgId/files`). */
export function OrgFilesPage() {
  const strings = useStrings();
  const orgLabelCap = useOrgLabelCapitalized();
  const { orgId } = useParams<{ orgId: string }>();
  const [files, setFiles] = useState<ProjectFile[] | null>(null);
  const [total, setTotal] = useState(0);
  const [truncated, setTruncated] = useState(false);
  const [uploaders, setUploaders] = useState<ProjectFileUploader[]>([]);
  const [projects, setProjects] = useState<OrganizationFileProject[]>([]);
  const filters = useFileFilters();
  const [project, setProject] = useUrlText("project");
  const [archived, setArchived] = useUrlFlag("archived");
  const limitFor = useRestoredRowCount(PAGE_SIZE);
  const latestRequest = useRef(0);

  async function loadFiles(offset: number, append: boolean) {
    if (!orgId) return;
    const request = ++latestRequest.current;
    const page = await api.postPage<ProjectFile>(
      `/api/v1/orgs/${orgId}/files/search?limit=${limitFor(offset)}&offset=${offset}`,
      { ...filters.body(), project_ids: project ? [project] : [], include_archived: archived },
    );
    if (request !== latestRequest.current) return;
    setFiles((prev) => (append && prev ? [...prev, ...page.items] : page.items));
    setTotal(page.total);
    setTruncated(Boolean(page.truncated));
  }

  const filterKey = [orgId, project, archived, ...filters.key];
  useResetOnChange(filterKey, () => setFiles(null));
  useLoadOnChange(() => loadFiles(0, false), filterKey);
  useLoadOnChange(async () => {
    if (!orgId) return;
    const query = `include_archived=${archived}`;
    const [people, choices] = await Promise.all([
      api.get<ProjectFileUploader[]>(`/api/v1/orgs/${orgId}/files/uploaders?${query}`),
      api.get<OrganizationFileProject[]>(`/api/v1/orgs/${orgId}/files/projects?${query}`),
    ]);
    setUploaders(people);
    setProjects(choices);
  }, [orgId, archived]);

  const filtered = filters.filtered || Boolean(project);

  return (
    <ListPageLayout
      ready={files !== null}
      loadedRows={files?.length}
      title={strings.files.orgTitle(orgLabelCap)}
      filter={
        <FilterPanel
          sectionKey="orgFilesFilters"
          search={filters.search}
          onSearchChange={filters.setSearch}
          searchPlaceholder={strings.files.searchPlaceholder}
          searchAriaLabel={strings.files.searchLabel}
        >
          <FilterSelect
            label={strings.files.filterProject}
            value={project}
            onChange={setProject}
            allLabel={strings.files.allProjects}
            options={projects.map((p) => ({ value: p.id, label: p.name }))}
          />
          <FileFilterFields filters={filters} uploaders={uploaders} />
          <FilterCheckbox label={strings.files.includeArchivedProjects} checked={archived} onChange={setArchived} />
        </FilterPanel>
      }
    >
      {!files && <Spinner />}
      {files && truncated && <p className="text-muted" role="status">{strings.files.projectsTruncated}</p>}
      {files && files.length === 0 && <p className="text-muted">{filtered ? strings.files.emptyFiltered : strings.files.orgEmpty}</p>}
      {files && files.length > 0 && <FilesTable files={files} showProject />}
      {files && <LoadMoreButton loaded={files.length} total={total} onClick={() => loadFiles(files.length, true)} />}
    </ListPageLayout>
  );
}
