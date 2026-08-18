import { Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { Organization, OrgImportResult } from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { FilterBadge } from "../components/FilterBadge";
import { FilterField, FilterPanel } from "../components/FilterPanel";
import { Spinner } from "../components/Spinner";
import { useOrgLabel, useOrgLabelCapitalized, useOrgLabelPlural } from "../context/BrandingContext";
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
  const orgLabel = useOrgLabel();
  const orgLabelCap = useOrgLabelCapitalized();
  const orgLabelPlural = useOrgLabelPlural();
  const [orgs, setOrgs] = useState<Organization[] | null>(null);
  const [search, setSearch] = useState("");
  // Defaults to "active" (C-A-13-adjacent hygiene): a deployment that's
  // been running a while accumulates disabled orgs (non-payment, offboarded
  // customers, ...) that would otherwise dominate a plain, unfiltered list.
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("active");
  const [showNewForm, setShowNewForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [importFile, setImportFile] = useState<File | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [importWarnings, setImportWarnings] = useState<string[] | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [deletingOrgId, setDeletingOrgId] = useState<string | null>(null);

  async function reload() {
    setOrgs(await api.get<Organization[]>("/api/v1/orgs"));
  }

  useEffect(() => {
    reload();
  }, []);

  async function createOrg() {
    setCreateError(null);
    try {
      if (importFile) {
        // Full-fidelity organisation bundle import (`services.org_export`)
        // — creates a brand-new organisation from an exported bundle
        // (settings, members, report templates, and every project's
        // structure/history), for backup restore, offboarding, or
        // cross-instance migration.
        const result = await api.postFile<OrgImportResult>("/api/v1/orgs/import", importFile, { name: newName });
        if (result.warnings.length > 0) setImportWarnings(result.warnings);
        setNewName("");
        setImportFile(null);
        setShowNewForm(false);
        reload();
        return;
      }
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
    setDeletingOrgId(org.id);
  }

  function cancelDelete() {
    setDeletingOrgId(null);
  }

  async function confirmDelete(org: Organization) {
    await runAction(async () => {
      await api.delete(`/api/v1/orgs/${org.id}`, { confirm_name: org.name });
    });
    setDeletingOrgId(null);
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
        <h1 style={{ margin: 0 }}>{strings.orgAdmin.organizations(orgLabelPlural)}</h1>
        <button className="btn btn-primary" onClick={() => setShowNewForm((v) => !v)}>
          <Plus size={16} /> New {orgLabel}
        </button>
      </div>

      {showNewForm && (
        <div className="card stack">
          <input
            className="input"
            placeholder={importFile ? `${orgLabelCap} name (optional — defaults to the bundle's own name)` : `${orgLabelCap} name`}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <label className="stack" style={{ gap: "0.25rem" }}>
            Or import from an exported {orgLabel} bundle (.zip)
            <input
              className="input" type="file" accept=".zip,application/zip"
              onChange={(e) => setImportFile(e.target.files?.[0] ?? null)}
            />
          </label>
          {createError && <div style={{ color: "var(--color-danger)" }}>{createError}</div>}
          <button
            className="btn btn-primary" onClick={createOrg} disabled={!importFile && !newName}
            style={{ alignSelf: "flex-start" }}
          >
            Create
          </button>
        </div>
      )}
      {importWarnings && importWarnings.length > 0 && (
        <div className="card stack" style={{ borderColor: "var(--color-warning, #b58900)" }}>
          <strong>Imported with warnings</strong>
          <ul style={{ margin: 0 }}>
            {importWarnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        </div>
      )}

      {actionError && <div style={{ color: "var(--color-danger)" }}>{actionError}</div>}

      <div className="side-grid">
        <div className="stack">
          <input
            className="input"
            style={{ maxWidth: 280 }}
            placeholder={strings.serverOrgs.search(orgLabelPlural)}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />

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
            {orgs.length === 0 && <p className="text-muted">No {orgLabelPlural.toLowerCase()} yet.</p>}
            {orgs.length > 0 && filteredOrgs.length === 0 && <p className="text-muted">{strings.serverOrgs.empty(orgLabelPlural)}</p>}
          </div>
        </div>

        <FilterPanel>
          <h2 style={{ margin: 0, fontSize: "1rem" }}>Filters</h2>
          <FilterField label="Status">
            <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}>
              <option value="active">{strings.serverOrgs.active}</option>
              <option value="disabled">{strings.serverOrgs.disabled}</option>
              <option value="all">{strings.serverOrgs.filterAll}</option>
            </select>
          </FilterField>
        </FilterPanel>
      </div>

      {deletingOrgId &&
        (() => {
          const org = orgs.find((o) => o.id === deletingOrgId);
          if (!org) return null;
          return (
            <ConfirmDialog
              title={strings.serverOrgs.deleteTitle(orgLabel)}
              message={strings.serverOrgs.deleteHint(org.name, orgLabel)}
              confirmLabel={strings.serverOrgs.deleteConfirmButton}
              requireTypedText={org.name}
              onConfirm={() => confirmDelete(org)}
              onCancel={cancelDelete}
            />
          );
        })()}
    </div>
  );
}
