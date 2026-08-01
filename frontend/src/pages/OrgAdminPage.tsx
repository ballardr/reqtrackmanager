import { Plus, Trash2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { api, fileUrl } from "../api/client";
import type { FileAsset, OrgGroup, OrgUser, Organization, ProjectListItem } from "../api/types";
import { Spinner } from "../components/Spinner";
import { t } from "../i18n/strings";

const strings = t();

/**
 * Organisation administration: users (C-U-01), groups (C-U-08), shared
 * resource files (C-M-03), the organisation logo (U-C-02), and the default
 * template project used for new projects (C-E-04).
 */
export function OrgAdminPage() {
  const { orgId } = useParams<{ orgId: string }>();
  const [org, setOrg] = useState<Organization | null>(null);
  const [users, setUsers] = useState<OrgUser[]>([]);
  const [groups, setGroups] = useState<OrgGroup[]>([]);
  const [resources, setResources] = useState<FileAsset[]>([]);
  const [templateProjects, setTemplateProjects] = useState<ProjectListItem[]>([]);

  const [newUserEmail, setNewUserEmail] = useState("");
  const [newUserName, setNewUserName] = useState("");
  const [newUserPassword, setNewUserPassword] = useState("");
  const [newGroupName, setNewGroupName] = useState("");
  const [groupMemberInputs, setGroupMemberInputs] = useState<Record<string, string>>({});

  const logoInputRef = useRef<HTMLInputElement>(null);
  const resourceInputRef = useRef<HTMLInputElement>(null);

  async function reload() {
    if (!orgId) return;
    const [o, u, g, r, projects] = await Promise.all([
      api.get<Organization>(`/api/v1/orgs/${orgId}`),
      api.get<OrgUser[]>(`/api/v1/orgs/${orgId}/users`),
      api.get<OrgGroup[]>(`/api/v1/orgs/${orgId}/groups`),
      api.get<FileAsset[]>(`/api/v1/orgs/${orgId}/resources`),
      api.get<ProjectListItem[]>("/api/v1/projects?archived=false"),
    ]);
    setOrg(o);
    setUsers(u);
    setGroups(g);
    setResources(r);
    setTemplateProjects(projects.filter((p) => p.is_template && p.organization_id === orgId));
  }

  async function setDefaultTemplate(projectId: string) {
    await api.put(`/api/v1/orgs/${orgId}/default-template`, { project_id: projectId || null });
    reload();
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId]);

  async function createUser() {
    await api.post(`/api/v1/orgs/${orgId}/users`, {
      email: newUserEmail, display_name: newUserName, password: newUserPassword, role: "member",
    });
    setNewUserEmail("");
    setNewUserName("");
    setNewUserPassword("");
    reload();
  }

  async function createGroup() {
    await api.post(`/api/v1/orgs/${orgId}/groups`, { name: newGroupName });
    setNewGroupName("");
    reload();
  }

  async function addGroupMember(groupId: string) {
    const userId = groupMemberInputs[groupId];
    if (!userId) return;
    await api.post(`/api/v1/orgs/${orgId}/groups/${groupId}/members`, { user_id: userId });
    setGroupMemberInputs((m) => ({ ...m, [groupId]: "" }));
    reload();
  }

  async function uploadLogo(file: File) {
    await api.postFile(`/api/v1/orgs/${orgId}/logo`, file);
    reload();
  }

  async function uploadResource(file: File) {
    await api.postFile(`/api/v1/orgs/${orgId}/resources`, file);
    reload();
  }

  async function deleteResource(fileId: string) {
    await api.delete(`/api/v1/orgs/${orgId}/resources/${fileId}`);
    reload();
  }

  if (!org) return <Spinner />;

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>{org.name}</h1>
        {org.logo_file_id && (
          <img src={fileUrl(org.logo_file_id)} alt={`${org.name} logo`} style={{ height: 40 }} />
        )}
      </div>

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.orgAdmin.logo}</h2>
        <input
          ref={logoInputRef}
          type="file"
          accept="image/*"
          onChange={(e) => e.target.files?.[0] && uploadLogo(e.target.files[0])}
        />
      </div>

      {templateProjects.length > 0 && (
        <div className="card stack">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.orgAdmin.defaultTemplate}</h2>
          <select
            className="input"
            value={org.default_template_project_id ?? ""}
            onChange={(e) => setDefaultTemplate(e.target.value)}
          >
            <option value="">{strings.projects.noTemplate}</option>
            {templateProjects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.orgAdmin.users}</h2>
        <table>
          <thead>
            <tr>
              <th>{strings.orgAdmin.email}</th>
              <th>{strings.orgAdmin.name}</th>
              <th>{strings.orgAdmin.roles}</th>
              <th>{strings.orgAdmin.status}</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.user_id}>
                <td>{u.email}</td>
                <td>{u.display_name}</td>
                <td>{u.roles.join(", ")}</td>
                <td>{u.is_archived ? "archived" : u.is_active ? "active" : "deactivated"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="row">
          <input className="input" placeholder={strings.orgAdmin.email} value={newUserEmail} onChange={(e) => setNewUserEmail(e.target.value)} />
          <input className="input" placeholder={strings.orgAdmin.name} value={newUserName} onChange={(e) => setNewUserName(e.target.value)} />
          <input className="input" type="password" placeholder={strings.orgAdmin.password} value={newUserPassword} onChange={(e) => setNewUserPassword(e.target.value)} />
          <button className="btn btn-primary" onClick={createUser} disabled={!newUserEmail || !newUserName || !newUserPassword}>
            <Plus size={14} /> {strings.orgAdmin.newUser}
          </button>
        </div>
      </div>

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.orgAdmin.groups}</h2>
        {groups.map((g) => (
          <div key={g.id} className="stack">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span>{g.name}</span>
              <span className="text-muted">{g.member_user_ids.length} members</span>
            </div>
            <div className="row">
              <input
                className="input"
                style={{ maxWidth: 280 }}
                placeholder="User ID"
                value={groupMemberInputs[g.id] ?? ""}
                onChange={(e) => setGroupMemberInputs((m) => ({ ...m, [g.id]: e.target.value }))}
              />
              <button className="btn" onClick={() => addGroupMember(g.id)}>
                {strings.admin.addMember}
              </button>
            </div>
          </div>
        ))}
        <div className="row">
          <input className="input" placeholder="Name" value={newGroupName} onChange={(e) => setNewGroupName(e.target.value)} />
          <button className="btn btn-primary" onClick={createGroup} disabled={!newGroupName}>
            <Plus size={14} /> {strings.orgAdmin.newGroup}
          </button>
        </div>
      </div>

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.orgAdmin.resources}</h2>
        {resources.map((r) => (
          <div key={r.id} className="row" style={{ justifyContent: "space-between" }}>
            <a href={fileUrl(r.id)} target="_blank" rel="noreferrer">
              {r.filename}
            </a>
            <button className="btn btn-danger" onClick={() => deleteResource(r.id)}>
              <Trash2 size={14} />
            </button>
          </div>
        ))}
        <input
          ref={resourceInputRef}
          type="file"
          onChange={(e) => e.target.files?.[0] && uploadResource(e.target.files[0])}
        />
        <span className="text-muted row">
          <Upload size={14} /> {strings.orgAdmin.resourcesHint}
        </span>
      </div>
    </div>
  );
}
