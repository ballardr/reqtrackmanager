import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { Organization } from "../api/types";
import { Spinner } from "../components/Spinner";
import { t } from "../i18n/strings";

const strings = t();

/** Lists organisations the user belongs to (C-U-15: users may belong to more than one). */
export function OrgListPage() {
  const [orgs, setOrgs] = useState<Organization[] | null>(null);

  useEffect(() => {
    api.get<Organization[]>("/api/v1/orgs").then(setOrgs);
  }, []);

  if (!orgs) return <Spinner />;

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>{strings.orgAdmin.organizations}</h1>
      <div className="card stack">
        {orgs.map((o) => (
          <Link key={o.id} to={`/orgs/${o.id}/admin`}>
            {o.name}
          </Link>
        ))}
        {orgs.length === 0 && <p className="text-muted">{strings.orgAdmin.noOrganizations}</p>}
      </div>
    </div>
  );
}
