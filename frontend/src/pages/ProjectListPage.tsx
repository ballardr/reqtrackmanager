import { Plus, Star } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../api/client";
import type { Organization, Project, ProjectListItem, ProjectRole, StageStatus } from "../api/types";
import { STAGE_STATUS_LABEL } from "../api/types";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { Spinner } from "../components/Spinner";
import { useViewMode, ViewToggle } from "../components/ViewToggle";
import { t } from "../i18n/strings";

const strings = t();

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
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectListItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [showArchived, setShowArchived] = useState(false);
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<ProjectRole | "">("");
  const [stageStatusFilter, setStageStatusFilter] = useState<StageStatus | "">("");
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [showNewForm, setShowNewForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [newSummary, setNewSummary] = useState("");
  const [newOrgId, setNewOrgId] = useState("");
  const [templateProjectId, setTemplateProjectId] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [allProjects, setAllProjects] = useState<ProjectListItem[]>([]);
  const [viewMode, setViewMode] = useViewMode("projects");

  function listParams(offset: number): URLSearchParams {
    const params = new URLSearchParams({ archived: String(showArchived), limit: String(PAGE_SIZE), offset: String(offset) });
    if (search) params.set("search", search);
    if (roleFilter) params.set("role", roleFilter);
    if (stageStatusFilter) params.set("stage_status", stageStatusFilter);
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
      api.get<Organization[]>("/api/v1/orgs"),
      api.get<ProjectListItem[]>("/api/v1/projects?archived=false"),
      loadProjects(0, false),
    ]);
    setOrgs(orgList);
    setAllProjects(everyProject);
    if (!newOrgId && orgList[0]) setNewOrgId(orgList[0].id);
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showArchived, search, roleFilter, stageStatusFilter]);

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
    if (project.is_favorite) {
      await api.delete(`/api/v1/projects/${project.id}/favorite`);
    } else {
      await api.put(`/api/v1/projects/${project.id}/favorite`);
    }
    reload();
  }

  const templateOptions = allProjects.filter((p) => p.is_template && p.organization_id === newOrgId);

  async function createProject() {
    setCreateError(null);
    try {
      const project = await api.post<Project>("/api/v1/projects", {
        organization_id: newOrgId,
        name: newName,
        summary: newSummary,
        template_project_id: templateProjectId || null,
      });
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
          {templateOptions.length > 0 && (
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
          {createError && <div style={{ color: "var(--color-danger)" }}>{createError}</div>}
          <button className="btn btn-primary" onClick={createProject} disabled={!newName || !newOrgId}>
            {strings.common.create}
          </button>
        </div>
      )}

      <div className="row">
        <input
          className="input"
          style={{ maxWidth: 280 }}
          placeholder={strings.projects.search}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <button className={`btn ${!showArchived ? "btn-primary" : ""}`} onClick={() => setShowArchived(false)}>
          {strings.projects.active}
        </button>
        <button className={`btn ${showArchived ? "btn-primary" : ""}`} onClick={() => setShowArchived(true)}>
          {strings.projects.archived}
        </button>
        <select className="input" value={roleFilter} onChange={(e) => setRoleFilter(e.target.value as ProjectRole | "")}>
          <option value="">{strings.projects.allRoles}</option>
          <option value="project_manager">project_manager</option>
          <option value="project_administrator">project_administrator</option>
          <option value="stakeholder">stakeholder</option>
          <option value="member">member</option>
        </select>
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
        <ViewToggle mode={viewMode} onChange={setViewMode} />
      </div>

      {!projects && <Spinner />}
      {projects && projects.length === 0 && <p className="text-muted">{strings.projects.empty}</p>}
      {projects && projects.length > 0 && viewMode === "tiles" && (
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" }}>
          {projects.map((p) => (
            <div key={p.id} className="card stack" style={{ gap: "0.5rem" }}>
              <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                <Link to={`/projects/${p.id}`} style={{ fontWeight: 600, fontSize: "1.05rem" }}>
                  {p.name}
                </Link>
                <button
                  className="btn"
                  onClick={() => toggleFavorite(p)}
                  title={p.is_favorite ? strings.projects.unfavorite : strings.projects.favorite}
                  aria-label={p.is_favorite ? strings.projects.unfavorite : strings.projects.favorite}
                >
                  <Star size={16} fill={p.is_favorite ? "currentColor" : "none"} />
                </button>
              </div>
              {p.current_stage_name && (
                <span className="badge" style={{ alignSelf: "flex-start" }}>
                  {stageBadgeText(p.current_stage_name, p.current_stage_status)}
                </span>
              )}
              <p className="text-muted" style={{ margin: 0, flex: 1 }}>
                {p.summary || "—"}
              </p>
              <div className="text-muted" style={{ fontSize: "0.85rem" }}>
                {strings.projects.roles}: {p.my_roles.join(", ") || "—"}
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
                <th>Stage</th>
                <th>{strings.projects.roles}</th>
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
                  <td>
                    {p.current_stage_name && (
                      <span className="badge">{stageBadgeText(p.current_stage_name, p.current_stage_status)}</span>
                    )}
                  </td>
                  <td className="text-muted">{p.my_roles.join(", ") || "—"}</td>
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
  );
}
