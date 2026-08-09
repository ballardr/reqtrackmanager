import { Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { Organization } from "../api/types";
import { FilterBadge } from "../components/FilterBadge";
import { Spinner } from "../components/Spinner";
import { t } from "../i18n/strings";

const strings = t();

/**
 * Server-admin console listing every organisation on the deployment
 * (`GET /orgs` already returns all orgs for a server admin, scoped to the
 * caller's own memberships for everyone else) plus creation, and the two
 * lifecycle actions available for an existing one:
 *
 * - **Disable/enable**: reversible, no data touched — blocks every org/
 *   project-scoped request for everyone, including the org's own admins,
 *   until re-enabled (e.g. a hosting customer stopped paying).
 * - **Delete**: irreversible, gated behind typing the organisation's exact
 *   name to confirm — permanently removes everything it owns (projects,
 *   requirements, files, ...). See docs/decisions.md's "Organisation
 *   disable and hard delete" section for the full design.
 */
type StatusFilter = "active" | "disabled" | "all";

export function ServerOrganisationsPage() {
  const [orgs, setOrgs] = useState<Organization[] | null>(null);
  const [search, setSearch] = useState("");
  // Defaults to "active" (C-A-13-adjacent hygiene): a deployment that's
  // been running a while accumulates disabled orgs (non-payment, offboarded
  // customers, ...) that would otherwise dominate a plain, unfiltered list.
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("active");
  const [showNewForm, setShowNewForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [deletingOrgId, setDeletingOrgId] = useState<string | null>(null);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");

  async function reload() {
    setOrgs(await api.get<Organization[]>("/api/v1/orgs"));
  }

  useEffect(() => {
    reload();
  }, []);

  async function createOrg() {
    setCreateError(null);
    try {
      await api.post("/api/v1/orgs", { name: newName });
      setNewName("");
      setShowNewForm(false);
      reload();
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Something went wrong.");
    }
  }

  async function runAction(action: () => Promise<void>) {
    setActionError(null);
    try {
      await action();
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  function disableOrg(org: Organization) {
    if (!window.confirm(strings.serverOrgs.disableConfirm.replace("{name}", org.name))) return;
    runAction(() => api.post(`/api/v1/orgs/${org.id}/disable`));
  }

  function enableOrg(org: Organization) {
    runAction(() => api.post(`/api/v1/orgs/${org.id}/enable`));
  }

  function startDelete(org: Organization) {
    setActionError(null);
    setDeleteConfirmText("");
    setDeletingOrgId(org.id);
  }

  function cancelDelete() {
    setDeletingOrgId(null);
    setDeleteConfirmText("");
  }

  async function confirmDelete(org: Organization) {
    await runAction(async () => {
      await api.delete(`/api/v1/orgs/${org.id}`, { confirm_name: deleteConfirmText });
    });
    setDeletingOrgId(null);
    setDeleteConfirmText("");
  }

  if (!orgs) return <Spinner />;

  const filteredOrgs = orgs.filter((o) => {
    if (statusFilter === "active" && !o.is_active) return false;
    if (statusFilter === "disabled" && o.is_active) return false;
    if (search && !o.name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>{strings.orgAdmin.organizations}</h1>
        <button className="btn btn-primary" onClick={() => setShowNewForm((v) => !v)}>
          <Plus size={16} /> New organisation
        </button>
      </div>

      <div className="row">
        <input
          className="input"
          style={{ maxWidth: 280 }}
          placeholder={strings.serverOrgs.search}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <button className={`btn ${statusFilter === "active" ? "btn-primary" : ""}`} onClick={() => setStatusFilter("active")}>
          {strings.serverOrgs.active}
        </button>
        <button className={`btn ${statusFilter === "disabled" ? "btn-primary" : ""}`} onClick={() => setStatusFilter("disabled")}>
          {strings.serverOrgs.disabled}
        </button>
        <button className={`btn ${statusFilter === "all" ? "btn-primary" : ""}`} onClick={() => setStatusFilter("all")}>
          {strings.serverOrgs.filterAll}
        </button>
      </div>

      {showNewForm && (
        <div className="card stack">
          <input className="input" placeholder="Organisation name" value={newName} onChange={(e) => setNewName(e.target.value)} />
          {createError && <div style={{ color: "var(--color-danger)" }}>{createError}</div>}
          <button className="btn btn-primary" onClick={createOrg} disabled={!newName} style={{ alignSelf: "flex-start" }}>
            Create
          </button>
        </div>
      )}

      {actionError && <div style={{ color: "var(--color-danger)" }}>{actionError}</div>}

      <div className="card" style={{ overflowX: "auto" }}>
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th>Created</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {filteredOrgs.map((o) => (
              <tr key={o.id}>
                <td>{o.name}</td>
                <td>
                  {o.is_active ? (
                    <FilterBadge active={statusFilter === "active"} onClick={() => setStatusFilter("active")}>
                      {strings.serverOrgs.active}
                    </FilterBadge>
                  ) : (
                    <FilterBadge
                      active={statusFilter === "disabled"}
                      onClick={() => setStatusFilter("disabled")}
                      style={{ color: "var(--color-danger)", borderColor: "var(--color-danger)" }}
                    >
                      {strings.serverOrgs.disabled}
                    </FilterBadge>
                  )}
                </td>
                <td className="text-muted">{new Date(o.created_at).toLocaleDateString()}</td>
                <td>
                  <div className="row" style={{ gap: "0.4rem", justifyContent: "flex-end" }}>
                    <Link to={`/orgs/${o.id}/admin`} className="btn">
                      Edit
                    </Link>
                    {o.is_active ? (
                      <button className="btn" onClick={() => disableOrg(o)}>
                        {strings.serverOrgs.disable}
                      </button>
                    ) : (
                      <button className="btn" onClick={() => enableOrg(o)}>
                        {strings.serverOrgs.enable}
                      </button>
                    )}
                    <button className="btn btn-danger" onClick={() => startDelete(o)}>
                      {strings.serverOrgs.delete}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {orgs.length === 0 && <p className="text-muted">No organisations yet.</p>}
        {orgs.length > 0 && filteredOrgs.length === 0 && <p className="text-muted">{strings.serverOrgs.empty}</p>}
      </div>

      {deletingOrgId &&
        (() => {
          const org = orgs.find((o) => o.id === deletingOrgId);
          if (!org) return null;
          return (
            <div className="card stack" style={{ borderColor: "var(--color-danger)" }}>
              <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.serverOrgs.deleteTitle}</h2>
              <p className="text-muted">{strings.serverOrgs.deleteHint.replace("{name}", org.name)}</p>
              <input
                className="input"
                placeholder={org.name}
                value={deleteConfirmText}
                onChange={(e) => setDeleteConfirmText(e.target.value)}
              />
              <div className="row">
                <button
                  className="btn btn-danger"
                  onClick={() => confirmDelete(org)}
                  disabled={deleteConfirmText !== org.name}
                >
                  {strings.serverOrgs.deleteConfirmButton}
                </button>
                <button className="btn" onClick={cancelDelete}>
                  {strings.common.cancel}
                </button>
              </div>
            </div>
          );
        })()}
    </div>
  );
}
