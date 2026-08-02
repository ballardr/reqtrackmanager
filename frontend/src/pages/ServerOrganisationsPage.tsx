import { Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { Organization } from "../api/types";
import { Spinner } from "../components/Spinner";

/**
 * Server-admin console listing every organisation on the deployment
 * (`GET /orgs` already returns all orgs for a server admin, scoped to the
 * caller's own memberships for everyone else) plus creation. Deletion is
 * intentionally not offered here: an organisation can own an unbounded
 * number of projects/requirements, and there is no archive concept for
 * organisations (unlike projects) to make removal safely reversible.
 */
export function ServerOrganisationsPage() {
  const [orgs, setOrgs] = useState<Organization[] | null>(null);
  const [showNewForm, setShowNewForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);

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

  if (!orgs) return <Spinner />;

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>Organisations</h1>
        <button className="btn btn-primary" onClick={() => setShowNewForm((v) => !v)}>
          <Plus size={16} /> New organisation
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

      <div className="card" style={{ overflowX: "auto" }}>
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Created</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {orgs.map((o) => (
              <tr key={o.id}>
                <td>{o.name}</td>
                <td className="text-muted">{new Date(o.created_at).toLocaleDateString()}</td>
                <td>
                  <Link to={`/orgs/${o.id}/admin`} className="btn">
                    Edit
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {orgs.length === 0 && <p className="text-muted">No organisations yet.</p>}
      </div>
    </div>
  );
}
