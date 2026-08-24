import { Plus, Star } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../api/client";
import type { Organization, Project, ProjectImportResult, ProjectListItem, ProjectRole, StageStatus } from "../api/types";
import { PROJECT_ROLE_LABEL, STAGE_STATUS_LABEL } from "../api/types";
import { FilterBadge } from "../components/FilterBadge";
import { FilterField, FilterPanel } from "../components/FilterPanel";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { Spinner } from "../components/Spinner";
import { useViewMode, ViewToggle } from "../components/ViewToggle";
import { useAuth } from "../context/AuthContext";
import { useOrgLabel, useOrgLabelCapitalized, useOrgLabelPlural } from "../context/BrandingContext";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";

const PAGE_SIZE = 30;

function stageBadgeText(stageName: string, status: StageStatus | null): string {
  if (!status || stageName.toLowerCase() === status) return stageName;
  return `${stageName} · ${STAGE_STATUS_LABEL[status]}`;
}

/**
 * Project list view (U-E-03): active projects across all organisations the
 * user can access, with an archived filter (U-E-04), search, project
 * creation (C-G-02), and incremental "load more" pagination (U-P-06).
 */
export function ProjectListPage() {
  const strings = useStrings();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { showToast } = useToast();
  const orgLabel = useOrgLabel();
  const orgLabelPlural = useOrgLabelPlural();
  const orgLabelCap = useOrgLabelCapitalized();
  const [projects, setProjects] = useState<ProjectListItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [showArchived, setShowArchived] = useState(false);
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<ProjectRole | "">("");
  const [stageStatusFilter, setStageStatusFilter] = useState<StageStatus | "">("");
  const [orgFilter, setOrgFilter] = useState("");
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [showNewForm, setShowNewForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [newSummary, setNewSummary] = useState("");
  const [newOrgId, setNewOrgId] = useState("");
  const [templateProjectId, setTemplateProjectId] = useState("");
  const [newVisibility, setNewVisibility] = useState<"only_specified" | "org_wide">("only_specified");
  const [importFile, setImportFile] = useState<File | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [importWarnings, setImportWarnings] = useState<string[] | null>(null);
  const [allProjects, setAllProjects] = useState<ProjectListItem[]>([]);
  const [viewMode, setViewMode] = useViewMode("projects");

  function listParams(offset: number): URLSearchParams {
    const params = new URLSearchParams({ archived: String(showArchived), limit: String(PAGE_SIZE), offset: String(offset) });
    if (search) params.set("search", search);
    if (roleFilter) params.set("role", roleFilter);
    if (stageStatusFilter) params.set("stage_status", stageStatusFilter);
    if (orgFilter) params.set("organization_id", orgFilter);
    return params;
  }

  async function loadProjects(offset: number, append: boolean) {
    const page = await api.getPage<ProjectListItem>(`/api/v1/projects?${listParams(offset).toString()}`);
    setProjects((prev) => (append && prev ? [...prev, ...page.items] : page.items));
    setTotal(page.total);
  }

  async function reload() {
    setProjects(null);
    const [orgList, everyProject] = await Promise.all([
      // `mine=true`: a server admin otherwise sees every organisation in the
      // deployment here (the plain `GET /orgs` directory-listing bypass,
      // meant for the platform-level org directory) rather than just the
      // ones they can actually create a project in or usefully filter by.
      api.get<Organization[]>("/api/v1/orgs?mine=true"),
      api.get<ProjectListItem[]>("/api/v1/projects?archived=false"),
      loadProjects(0, false),
    ]);
    // A disabled org can't hold any (newly) visible projects (the list
    // endpoint itself now excludes them) and can't accept new ones either
    // (`rbac._require_org_active`) — filtered out here so it doesn't appear
    // as a dead option in either the org filter or the "new project" org
    // picker below.
    const activeOrgs = orgList.filter((o) => o.is_active);
    setOrgs(activeOrgs);
    setAllProjects(everyProject);
    if (!newOrgId && activeOrgs[0]) setNewOrgId(activeOrgs[0].id);
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showArchived, search, roleFilter, stageStatusFilter, orgFilter]);

  useEffect(() => {
    // C-E-04: pre-select the organisation's default template project (if
    // one is configured) whenever the target org changes, rather than
    // always starting from "None". The user can still pick a different
    // template or explicitly choose "None (blank project)" before creating.
    const org = orgs.find((o) => o.id === newOrgId);
    setTemplateProjectId(org?.default_template_project_id ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [newOrgId]);

  async function toggleFavorite(project: ProjectListItem) {
    try {
      if (project.is_favorite) {
        await api.delete(`/api/v1/projects/${project.id}/favorite`);
      } else {
        await api.put(`/api/v1/projects/${project.id}/favorite`);
      }
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  const templateOptions = allProjects.filter((p) => p.is_template && p.organization_id === newOrgId);
  const showOrgColumn = orgs.length > 1 || !!user?.is_server_admin;

  function toggleStageStatusFilter(status: StageStatus | null) {
    if (!status) return;
    setStageStatusFilter((current) => (current === status ? "" : status));
  }

  async function createProject() {
    setCreateError(null);
    try {
      if (importFile) {
        // Full-fidelity project bundle import (`services.project_export`) —
        // a distinct path from template cloning: the bundle carries its own
        // structure/history and may have been exported from a different
        // organisation entirely, so it goes to a dedicated endpoint rather
        // than reusing `template_project_id`.
        const result = await api.postFile<ProjectImportResult>("/api/v1/projects/import", importFile, {
          organization_id: newOrgId, name: newName, summary: newSummary,
        });
        if (result.warnings.length > 0) setImportWarnings(result.warnings);
        showToast(strings.projects.created);
        navigate(`/projects/${result.project.id}`);
        return;
      }
      const project = await api.post<Project>("/api/v1/projects", {
        organization_id: newOrgId,
        name: newName,
        summary: newSummary,
        template_project_id: templateProjectId || null,
        visibility: newVisibility,
      });
      showToast(strings.projects.created);
      navigate(`/projects/${project.id}`);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>{strings.projects.title}</h1>
        <button className="btn btn-primary" onClick={() => setShowNewForm((v) => !v)}>
          <Plus size={16} /> {strings.projects.newProject}
        </button>
      </div>

      {showNewForm && (
        <div className="card stack">
          {orgs.length > 1 && (
            <select className="input" value={newOrgId} onChange={(e) => setNewOrgId(e.target.value)}>
              {orgs.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          )}
          <input
            className="input"
            placeholder={strings.projects.name}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <textarea
            className="input"
            rows={2}
            placeholder={strings.projects.summary}
            value={newSummary}
            onChange={(e) => setNewSummary(e.target.value)}
          />
          {templateOptions.length > 0 && !importFile && (
            <label className="stack" style={{ gap: "0.25rem" }}>
              {strings.projects.useTemplate}
              <select className="input" value={templateProjectId} onChange={(e) => setTemplateProjectId(e.target.value)}>
                <option value="">{strings.projects.noTemplate}</option>
                {templateOptions.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.admin.visibility}
            <select
              className="input"
              value={newVisibility}
              onChange={(e) => setNewVisibility(e.target.value as "only_specified" | "org_wide")}
            >
              <option value="only_specified">{strings.admin.visibilityOnlySpecified}</option>
              <option value="org_wide">{strings.admin.visibilityOrgWide}</option>
            </select>
          </label>
          <p className="text-muted" style={{ margin: 0, fontSize: "0.8rem" }}>{strings.admin.visibilityHint(orgLabel)}</p>
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.projects.importFromBundle}
            <input
              className="input" type="file" accept=".zip,application/zip"
              onChange={(e) => setImportFile(e.target.files?.[0] ?? null)}
            />
          </label>
          {createError && <div style={{ color: "var(--color-danger)" }}>{createError}</div>}
          <button className="btn btn-primary" onClick={createProject} disabled={!newName || !newOrgId}>
            {strings.common.create}
          </button>
        </div>
      )}
      {importWarnings && importWarnings.length > 0 && (
        <div className="card stack" style={{ borderColor: "var(--color-warning, #b58900)" }}>
          <strong>{strings.projects.importWarnings}</strong>
          <ul style={{ margin: 0 }}>
            {importWarnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        </div>
      )}

      <div className="side-grid">
        <div className="stack">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <input
              className="input"
              style={{ maxWidth: 280 }}
              placeholder={strings.projects.search}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <ViewToggle mode={viewMode} onChange={setViewMode} />
          </div>

          {!projects && <Spinner />}
          {projects && projects.length === 0 && <p className="text-muted">{strings.projects.empty}</p>}
          {projects && projects.length > 0 && viewMode === "tiles" && (
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(min(280px, 100%), 1fr))" }}>
              {projects.map((p) => (
                <div key={p.id} className="card stack" style={{ gap: "0.5rem" }}>
                  <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", flexWrap: "nowrap" }}>
                    <Link
                      to={`/projects/${p.id}`}
                      style={{
                        fontWeight: 600, fontSize: "1.05rem", minWidth: 0, overflow: "hidden",
                        textOverflow: "ellipsis", whiteSpace: "nowrap",
                      }}
                      title={p.name}
                    >
                      {p.name}
                    </Link>
                    <button
                      className="btn"
                      onClick={() => toggleFavorite(p)}
                      title={p.is_favorite ? strings.projects.unfavorite : strings.projects.favorite}
                      aria-label={p.is_favorite ? strings.projects.unfavorite : strings.projects.favorite}
                      style={{ flexShrink: 0 }}
                    >
                      <Star size={16} fill={p.is_favorite ? "currentColor" : "none"} />
                    </button>
                  </div>
                  {showOrgColumn && <div className="text-muted" style={{ fontSize: "0.8rem" }}>{p.organization_name}</div>}
                  {p.current_stage_name && (
                    <FilterBadge
                      active={stageStatusFilter === p.current_stage_status}
                      onClick={() => toggleStageStatusFilter(p.current_stage_status)}
                      style={{ alignSelf: "flex-start" }}
                    >
                      {stageBadgeText(p.current_stage_name, p.current_stage_status)}
                    </FilterBadge>
                  )}
                  <p className="text-muted" style={{ margin: 0, flex: 1 }}>
                    {p.summary || "—"}
                  </p>
                  <div className="text-muted" style={{ fontSize: "0.85rem" }}>
                    {strings.projects.roles}: {p.my_roles.map((r) => PROJECT_ROLE_LABEL[r]).join(", ") || "—"}
                  </div>
                  <div className="text-muted" style={{ fontSize: "0.85rem" }}>
                    {strings.projects.requirementCount}: {p.requirement_count}
                  </div>
                  <div className="text-muted" style={{ fontSize: "0.8rem" }}>
                    {strings.projects.updated}: {new Date(p.updated_at).toLocaleString()}
                  </div>
                </div>
              ))}
            </div>
          )}
          {projects && projects.length > 0 && viewMode === "list" && (
            <div className="card" style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th />
                    <th>Name</th>
                    {showOrgColumn && <th>{strings.projects.organisation(orgLabelCap)}</th>}
                    <th>{strings.projects.stage}</th>
                    <th>{strings.projects.roles}</th>
                    <th>{strings.projects.requirementCount}</th>
                    <th>{strings.projects.updated}</th>
                  </tr>
                </thead>
                <tbody>
                  {projects.map((p) => (
                    <tr key={p.id}>
                      <td>
                        <button
                          className="btn"
                          onClick={() => toggleFavorite(p)}
                          title={p.is_favorite ? strings.projects.unfavorite : strings.projects.favorite}
                          aria-label={p.is_favorite ? strings.projects.unfavorite : strings.projects.favorite}
                        >
                          <Star size={14} fill={p.is_favorite ? "currentColor" : "none"} />
                        </button>
                      </td>
                      <td>
                        <Link to={`/projects/${p.id}`}>{p.name}</Link>
                        <div className="text-muted" style={{ fontSize: "0.85rem" }}>
                          {p.summary || "—"}
                        </div>
                      </td>
                      {showOrgColumn && <td className="text-muted">{p.organization_name}</td>}
                      <td>
                        {p.current_stage_name && (
                          <FilterBadge
                            active={stageStatusFilter === p.current_stage_status}
                            onClick={() => toggleStageStatusFilter(p.current_stage_status)}
                          >
                            {stageBadgeText(p.current_stage_name, p.current_stage_status)}
                          </FilterBadge>
                        )}
                      </td>
                      <td className="text-muted">{p.my_roles.map((r) => PROJECT_ROLE_LABEL[r]).join(", ") || "—"}</td>
                      <td className="text-muted">{p.requirement_count}</td>
                      <td className="text-muted">{new Date(p.updated_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {projects && (
            <LoadMoreButton loaded={projects.length} total={total} onClick={() => loadProjects(projects.length, true)} />
          )}
        </div>

        <FilterPanel>
          <h2 style={{ margin: 0, fontSize: "1rem" }}>Filters</h2>
          <FilterField label="Status">
            <select className="input" value={showArchived ? "archived" : "active"} onChange={(e) => setShowArchived(e.target.value === "archived")}>
              <option value="active">{strings.projects.active}</option>
              <option value="archived">{strings.projects.archived}</option>
            </select>
          </FilterField>
          {orgs.length > 1 && (
            <FilterField label="Organisation">
              <select className="input" value={orgFilter} onChange={(e) => setOrgFilter(e.target.value)}>
                <option value="">{strings.projects.allOrganisations(orgLabelPlural)}</option>
                {orgs.map((o) => (
                  <option key={o.id} value={o.id}>{o.name}</option>
                ))}
              </select>
            </FilterField>
          )}
          <FilterField label="Role">
            <select className="input" value={roleFilter} onChange={(e) => setRoleFilter(e.target.value as ProjectRole | "")}>
              <option value="">{strings.projects.allRoles}</option>
              <option value="project_manager">{PROJECT_ROLE_LABEL.project_manager}</option>
              <option value="project_administrator">{PROJECT_ROLE_LABEL.project_administrator}</option>
              <option value="stakeholder">{PROJECT_ROLE_LABEL.stakeholder}</option>
              <option value="member">{PROJECT_ROLE_LABEL.member}</option>
            </select>
          </FilterField>
          <FilterField label={strings.projects.stageStatusLabel}>
            <select
              className="input"
              value={stageStatusFilter}
              onChange={(e) => setStageStatusFilter(e.target.value as StageStatus | "")}
            >
              <option value="">{strings.projects.allStages}</option>
              <option value="scoping">{STAGE_STATUS_LABEL.scoping}</option>
              <option value="review">{STAGE_STATUS_LABEL.review}</option>
              <option value="approved">{STAGE_STATUS_LABEL.approved}</option>
              <option value="completed">{STAGE_STATUS_LABEL.completed}</option>
              <option value="archived">{STAGE_STATUS_LABEL.archived}</option>
            </select>
          </FilterField>
        </FilterPanel>
      </div>
    </div>
  );
}
