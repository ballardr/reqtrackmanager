import { Lock, Plus, Trash2, Unlock, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { ApiError, api, fileUrl } from "../api/client";
import type { FileAsset, OrgAdvancedSettings, OrgGroup, OrgRole, OrgUser, Organization, ProjectListItem } from "../api/types";
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

  const [advanced, setAdvanced] = useState<OrgAdvancedSettings | null>(null);
  const [smtpHost, setSmtpHost] = useState("");
  const [smtpPort, setSmtpPort] = useState("");
  const [smtpUsername, setSmtpUsername] = useState("");
  const [smtpPassword, setSmtpPassword] = useState("");
  const [smtpUseTls, setSmtpUseTls] = useState(true);
  const [newMappingGroup, setNewMappingGroup] = useState("");
  const [newMappingRole, setNewMappingRole] = useState<OrgRole>("member");
  const [advancedError, setAdvancedError] = useState<string | null>(null);

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

    try {
      const a = await api.get<OrgAdvancedSettings>(`/api/v1/orgs/${orgId}/advanced-settings`);
      setAdvanced(a);
      setSmtpHost(a.smtp_host ?? "");
      setSmtpPort(a.smtp_port ? String(a.smtp_port) : "");
      setSmtpUsername(a.smtp_username ?? "");
      setSmtpUseTls(a.smtp_use_tls);
    } catch (err) {
      // Non-admins can't read advanced settings (403) — the section is simply hidden for them.
      if (!(err instanceof ApiError && err.status === 403)) throw err;
    }
  }

  async function saveAdvanced() {
    if (!orgId) return;
    setAdvancedError(null);
    try {
      const saved = await api.put<OrgAdvancedSettings>(`/api/v1/orgs/${orgId}/advanced-settings`, {
        smtp_host: smtpHost || null,
        smtp_port: smtpPort ? Number(smtpPort) : null,
        smtp_username: smtpUsername || null,
        smtp_password: smtpPassword || undefined,
        smtp_use_tls: smtpUseTls,
        sso_group_mappings: advanced?.sso_group_mappings ?? [],
      });
      setAdvanced(saved);
      setSmtpPassword("");
    } catch (err) {
      setAdvancedError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  function addMapping() {
    if (!newMappingGroup || !advanced) return;
    setAdvanced({
      ...advanced,
      sso_group_mappings: [...advanced.sso_group_mappings, { sso_group: newMappingGroup, org_role: newMappingRole }],
    });
    setNewMappingGroup("");
  }

  function removeMapping(idx: number) {
    if (!advanced) return;
    setAdvanced({ ...advanced, sso_group_mappings: advanced.sso_group_mappings.filter((_, i) => i !== idx) });
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

  async function toggleDisplayNameLock(user: OrgUser) {
    await api.put(`/api/v1/orgs/${orgId}/users/${user.user_id}/display-name-lock`, {
      display_name_locked: !user.display_name_locked,
    });
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
              <th></th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.user_id}>
                <td>{u.email}</td>
                <td>{u.display_name}</td>
                <td>{u.roles.join(", ")}</td>
                <td>{u.is_archived ? "archived" : u.is_active ? "active" : "deactivated"}</td>
                <td>
                  <button
                    className="btn"
                    onClick={() => toggleDisplayNameLock(u)}
                    title={u.display_name_locked ? strings.orgAdmin.unlockDisplayName : strings.orgAdmin.lockDisplayName}
                  >
                    {u.display_name_locked ? <Lock size={14} /> : <Unlock size={14} />}
                  </button>
                </td>
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
                placeholder={strings.admin.userId}
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
          <input className="input" placeholder={strings.admin.name} value={newGroupName} onChange={(e) => setNewGroupName(e.target.value)} />
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

      {advanced && (
        <div className="card stack">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.orgAdmin.advanced}</h2>
          <div className="row">
            <input
              className="input"
              placeholder={strings.orgAdmin.smtpHost}
              value={smtpHost}
              onChange={(e) => setSmtpHost(e.target.value)}
            />
            <input
              className="input"
              style={{ maxWidth: 120 }}
              placeholder={strings.orgAdmin.smtpPort}
              value={smtpPort}
              onChange={(e) => setSmtpPort(e.target.value)}
            />
          </div>
          <div className="row">
            <input
              className="input"
              placeholder={strings.orgAdmin.smtpUsername}
              value={smtpUsername}
              onChange={(e) => setSmtpUsername(e.target.value)}
            />
            <input
              className="input"
              type="password"
              placeholder={strings.orgAdmin.smtpPassword}
              value={smtpPassword}
              onChange={(e) => setSmtpPassword(e.target.value)}
            />
          </div>
          <label className="row">
            <input type="checkbox" checked={smtpUseTls} onChange={(e) => setSmtpUseTls(e.target.checked)} />
            {strings.orgAdmin.smtpUseTls}
          </label>

          <div className="stack">
            <strong>{strings.orgAdmin.ssoMappings}</strong>
            {advanced.sso_group_mappings.map((m, idx) => (
              <div key={idx} className="row" style={{ justifyContent: "space-between" }}>
                <span>
                  {m.sso_group} <span className="badge">{m.org_role}</span>
                </span>
                <button className="btn btn-danger" onClick={() => removeMapping(idx)}>
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            <div className="row">
              <input
                className="input"
                placeholder={strings.orgAdmin.ssoGroup}
                value={newMappingGroup}
                onChange={(e) => setNewMappingGroup(e.target.value)}
              />
              <select className="input" value={newMappingRole} onChange={(e) => setNewMappingRole(e.target.value as OrgRole)}>
                <option value="member">member</option>
                <option value="project_creator">project_creator</option>
                <option value="org_admin">org_admin</option>
              </select>
              <button className="btn" onClick={addMapping} disabled={!newMappingGroup}>
                <Plus size={14} /> {strings.orgAdmin.addMapping}
              </button>
            </div>
          </div>

          {advancedError && <div style={{ color: "var(--color-danger)" }}>{advancedError}</div>}
          <button className="btn btn-primary" onClick={saveAdvanced} style={{ alignSelf: "flex-start" }}>
            {strings.orgAdmin.saveAdvanced}
          </button>
        </div>
      )}
    </div>
  );
}
