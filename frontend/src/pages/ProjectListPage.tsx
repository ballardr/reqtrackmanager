import { Plus, Star } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../api/client";
import type { Organization, Project, ProjectListItem, ProjectRole, StageStatus } from "../api/types";
import { Spinner } from "../components/Spinner";
import { t } from "../i18n/strings";

const strings = t();

/**
 * Project list view (U-E-03): active projects across all organisations the
 * user can access, with an archived filter (U-E-04), search, and project
 * creation (C-G-02).
 */
export function ProjectListPage() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectListItem[] | null>(null);
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

  async function reload() {
    setProjects(null);
    const params = new URLSearchParams({ archived: String(showArchived) });
    if (search) params.set("search", search);
    if (roleFilter) params.set("role", roleFilter);
    if (stageStatusFilter) params.set("stage_status", stageStatusFilter);
    const [projectList, orgList, everyProject] = await Promise.all([
      api.get<ProjectListItem[]>(`/api/v1/projects?${params.toString()}`),
      api.get<Organization[]>("/api/v1/orgs"),
      api.get<ProjectListItem[]>("/api/v1/projects?archived=false"),
    ]);
    setProjects(projectList);
    setOrgs(orgList);
    setAllProjects(everyProject);
    if (!newOrgId && orgList[0]) setNewOrgId(orgList[0].id);
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showArchived, search, roleFilter, stageStatusFilter]);

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
          <option value="scoping">scoping</option>
          <option value="review">review</option>
          <option value="approved">approved</option>
          <option value="completed">completed</option>
        </select>
      </div>

      {!projects && <Spinner />}
      {projects && projects.length === 0 && <p className="text-muted">{strings.projects.empty}</p>}
      {projects && projects.length > 0 && (
        <div className="card" style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th></th>
                <th>{strings.projects.name}</th>
                <th>{strings.projects.summary}</th>
                <th>{strings.projects.stage}</th>
                <th>{strings.projects.updated}</th>
                <th>{strings.projects.roles}</th>
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
                      <Star size={16} fill={p.is_favorite ? "currentColor" : "none"} />
                    </button>
                  </td>
                  <td>
                    <Link to={`/projects/${p.id}`}>{p.name}</Link>
                  </td>
                  <td>{p.summary}</td>
                  <td>
                    {p.current_stage_name ? (
                      <span className="badge">
                        {p.current_stage_name} · {p.current_stage_status}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>{new Date(p.updated_at).toLocaleString()}</td>
                  <td>{p.my_roles.join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
