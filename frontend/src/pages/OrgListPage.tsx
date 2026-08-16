import { useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";

import { api } from "../api/client";
import type { Organization } from "../api/types";
import { Spinner } from "../components/Spinner";
import { useOrgLabelPlural } from "../context/BrandingContext";
import { t } from "../i18n/strings";

const strings = t();

/**
 * Lists organisations the user belongs to (C-U-15: users may belong to
 * more than one). A user who belongs to exactly one skips the list
 * entirely and lands straight on that organisation's admin page — the
 * list only earns its keep when there's an actual choice to make.
 */
export function OrgListPage() {
  const [orgs, setOrgs] = useState<Organization[] | null>(null);
  const orgLabelPlural = useOrgLabelPlural();

  useEffect(() => {
    api.get<Organization[]>("/api/v1/orgs").then(setOrgs);
  }, []);

  if (!orgs) return <Spinner />;

  if (orgs.length === 1) {
    return <Navigate to={`/orgs/${orgs[0].id}/admin`} replace />;
  }

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>Org Management</h1>
      <div className="card stack">
        {orgs.map((o) => (
          <Link key={o.id} to={`/orgs/${o.id}/admin`}>
            {o.name}
          </Link>
        ))}
        {orgs.length === 0 && <p className="text-muted">{strings.orgAdmin.noOrganizations(orgLabelPlural)}</p>}
      </div>
    </div>
  );
}
